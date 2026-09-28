from __future__ import annotations

from typing import Any, TYPE_CHECKING
from pathlib import Path
import math
import sys
import time

import numpy as np
import wgpu
from rendercanvas.glfw import RenderCanvas, loop

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scr"))

from camera2d import *
from colormaterial import *
from transform import *
from shape import *
from square import *
from node import *
from shader import *
from pipeline import *
from texture import *
from sampler import *
from textureset import *
from scene import *
from renderer import *
from engine import *

if TYPE_CHECKING:
  from state import State

canvas: RenderCanvas
device: wgpu.GPUDevice
context: Any
renderer: Renderer
camera: Camera2D
scene: Scene
last_t: float = 0.0

class Disk (Shape):

  def __init__ (self, device: wgpu.GPUDevice, nseg: int = 64) -> None:
    if nseg < 3:
      raise ValueError(f"Disk needs nseg >= 3, got {nseg}")
    coord = [[0.0, 0.0]]
    texcoord = [[0.5, 0.5]]
    for i in range(nseg):
      a = 2*math.pi*i/nseg
      c, s = math.cos(a), math.sin(a)
      coord.append([c, s])
      texcoord.append([0.5 + 0.5*c, 0.5 - 0.5*s])
    index: list[int] = []
    for i in range(nseg):
      index += [0, 1+i, 1+(i+1) % nseg]
    self.nind: int = len(index)
    bcoord = np.array(coord, dtype='float32')
    btexcoord = np.array(texcoord, dtype='float32')
    bindex = np.array(index, dtype='uint32')
    self.coord_vbo: wgpu.GPUBuffer = device.create_buffer_with_data(data=bcoord, usage=wgpu.BufferUsage.VERTEX)
    self.texcoord_vbo: wgpu.GPUBuffer = device.create_buffer_with_data(data=btexcoord, usage=wgpu.BufferUsage.VERTEX)
    self.ibo: wgpu.GPUBuffer = device.create_buffer_with_data(data=bindex, usage=wgpu.BufferUsage.INDEX)

  def draw (self, st: State) -> None:
    first_instance = st.get_shader().commit_matrix(st)
    st.render_pass.set_vertex_buffer(0, self.coord_vbo)
    st.render_pass.set_vertex_buffer(1, self.texcoord_vbo)
    st.render_pass.set_index_buffer(self.ibo, wgpu.IndexFormat.uint32)
    st.render_pass.draw_indexed(self.nind, 1, 0, 0, first_instance)

class Spin (Engine):

  def __init__ (self, trf: Transform, speed: float) -> None:
    self.trf = trf
    self.speed = speed

  def update (self, dt: float) -> None:
    self.trf.rotate(self.speed*dt, 0, 0, 1)

def textured (device: wgpu.GPUDevice, shader: Shader, sampler: Sampler, image: str) -> TextureSet:
  tex = Texture(device, "decal_texture", str(ROOT / "images" / image))
  ts = TextureSet([tex, sampler])
  shader.add_texture_set(ts)
  return ts

def body (disk: Disk, ts: TextureSet, radius: float) -> tuple[Node, Transform]:
  trf_scale = Transform()
  trf_scale.scale(radius, radius, 1)
  trf_spin = Transform()
  node = Node(trf=trf_spin, nodes=[Node(trf=trf_scale, apps=[ts], shps=[disk])])
  return node, trf_spin

def orbit (radius: float, nodes: list[Node]) -> tuple[Node, Transform]:
  trf_orbit = Transform()
  trf_radius = Transform()
  trf_radius.translate(radius, 0, 0)
  node = Node(trf=trf_orbit, nodes=[Node(trf=trf_radius, nodes=nodes)])
  return node, trf_orbit

def initialize (device: wgpu.GPUDevice, target_format: str) -> None:
  global camera, scene
  camera = Camera2D(-10,10,-10,10)

  shader = Shader(device, str(ROOT / "shaders" / "texture.wgsl"))
  shader.set_vertex_buffers([
    {"array_stride": 2 * 4, "step_mode": "vertex",
     "attributes": [{"format": "float32x2", "offset": 0, "var_name": "pos"}]},
    {"array_stride": 2 * 4, "step_mode": "vertex",
     "attributes": [{"format": "float32x2", "offset": 0, "var_name": "texcoord"}]},
  ])
  pipeline = Pipeline(shader, target_format, depth_stencil=None)

  white = ColorMaterial(1,1,1)
  shader.add_material(white)

  sampler = Sampler(device, "decal_sampler", address_mode_u="clamp-to-edge", address_mode_v="clamp-to-edge")
  space_tex = textured(device, shader, sampler, "space.jpg")
  sun_tex = textured(device, shader, sampler, "sun.jpg")
  venus_tex = textured(device, shader, sampler, "venus.jpg")
  earth_tex = textured(device, shader, sampler, "earth.png")
  moon_tex = textured(device, shader, sampler, "moon.jpg")

  disk = Disk(device)

  trf_space = Transform()
  trf_space.scale(20,20,1)
  space = Node(trf=trf_space, apps=[space_tex], shps=[Square(device)])

  sun, _ = body(disk, sun_tex, 2.0)

  venus, _ = body(disk, venus_tex, 0.6)
  venus_orbit, trf_venus_orbit = orbit(4.5, [venus])

  moon, _ = body(disk, moon_tex, 0.3)
  moon_orbit, trf_moon_orbit = orbit(1.6, [moon])

  earth, trf_earth_spin = body(disk, earth_tex, 0.9)
  earth_orbit, trf_earth_orbit = orbit(7.5, [earth, moon_orbit])

  root = Node(pipeline, apps=[white], nodes=[space, sun, venus_orbit, earth_orbit])
  scene = Scene(root)
  scene.add_engine(Spin(trf_earth_orbit, 15))
  scene.add_engine(Spin(trf_venus_orbit, 24))
  scene.add_engine(Spin(trf_earth_spin, 90))
  scene.add_engine(Spin(trf_moon_orbit, 120))

def update (dt: float) -> None:
  scene.update(dt)

def draw () -> None:
  global last_t
  t = time.perf_counter()
  update(t - last_t)
  last_t = t

  target_texture = context.get_current_texture()
  renderer.render(target_texture, scene, camera)

def on_key (event: Any) -> None:
  if event["key"] == "q":
    canvas.close()

def main () -> None:
  global canvas, device, context, renderer, last_t

  canvas = RenderCanvas(size=(700, 700), title="sistema solar", update_mode="continuous", max_fps=60)
  adapter = wgpu.gpu.request_adapter_sync()
  device = adapter.request_device_sync()
  context = canvas.get_context("wgpu")
  target_format = context.get_preferred_format(device.adapter)
  context.configure(device=device, format=target_format)

  renderer = Renderer(device, clear_value=(0.0, 0.0, 0.0, 1.0))

  initialize(device, target_format)

  canvas.add_event_handler(on_key, "key_down")
  last_t = time.perf_counter()
  canvas.request_draw(draw)
  loop.run()

if __name__ == "__main__":
  main()
