<script setup lang="ts">
// 3D 挂件：Shinano（VRChat FBX → GLB，draco+webp 压缩到 15MB）
// three.js + GLTFLoader + DRACOLoader；待机轻摇摆 + 视线/头部跟鼠标
import { ref, onMounted, onUnmounted } from "vue";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";
import { DRACOLoader } from "three/examples/jsm/loaders/DRACOLoader.js";

const emit = defineEmits<{ poke: [] }>();

const host = ref<HTMLElement | null>(null);
let renderer: THREE.WebGLRenderer | null = null;
let raf = 0;

onMounted(() => {
  const el = host.value!;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(32, el.clientWidth / el.clientHeight, 0.1, 50);
  camera.position.set(0, 1.25, 2.6);

  renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true });
  renderer.setSize(el.clientWidth, el.clientHeight);
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  el.appendChild(renderer.domElement);

  // 灯光：环境 + 主光 + 轮廓光
  scene.add(new THREE.HemisphereLight(0xc9d4e8, 0x14171f, 1.1));
  const key = new THREE.DirectionalLight(0xffffff, 1.4);
  key.position.set(2, 3, 2.5);
  scene.add(key);
  const rim = new THREE.DirectionalLight(0xe8a0bf, 0.5);
  rim.position.set(-2, 1.5, -2);
  scene.add(rim);

  const draco = new DRACOLoader().setDecoderPath("/draco/");
  const loader = new GLTFLoader().setDRACOLoader(draco);

  let model: THREE.Group | null = null;
  let head: THREE.Object3D | null = null;

  loader.load("/assets/shinano/Shinano-web.glb", (gltf: any) => {
    const m = gltf.scene as THREE.Group;
    model = m;
    // 居中：算包围盒，把模型摆到地面上、面向镜头
    const box = new THREE.Box3().setFromObject(m);
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    m.position.set(-center.x, -box.min.y, -center.z);
    const s = 1.9 / size.y;
    m.scale.setScalar(s);
    scene.add(m);

    // 找头骨做注视（VRChat 人形标准命名 Head）
    m.traverse((o: THREE.Object3D) => {
      if (!head && /head/i.test(o.name)) head = o;
    });
  });

  // 鼠标视差
  const mouse = { x: 0, y: 0 };
  const onMove = (e: MouseEvent) => {
    mouse.x = (e.clientX / innerWidth - 0.5) * 2;
    mouse.y = (e.clientY / innerHeight - 0.5) * 2;
  };
  window.addEventListener("mousemove", onMove);

  // 点击 → 戳一戳（播塔罗气泡）
  renderer.domElement.addEventListener("click", () => emit("poke"));

  const clock = new THREE.Clock();
  const tick = () => {
    raf = requestAnimationFrame(tick);
    const t = clock.getElapsedTime();
    if (model) {
      // 待机轻摇摆 + 呼吸
      model.rotation.y = Math.sin(t * 0.4) * 0.06 + mouse.x * 0.12;
      model.position.y += Math.sin(t * 1.6) * 0.0006;
      if (head) {
        head.rotation.y = THREE.MathUtils.lerp(head.rotation.y, mouse.x * 0.5, 0.06);
        head.rotation.x = THREE.MathUtils.lerp(head.rotation.x, -mouse.y * 0.25, 0.06);
      }
    }
    camera.lookAt(0, 1.1, 0);
    renderer!.render(scene, camera);
  };
  tick();

  const onResize = () => {
    if (!renderer) return;
    camera.aspect = el.clientWidth / el.clientHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(el.clientWidth, el.clientHeight);
  };
  const ro = new ResizeObserver(onResize);
  ro.observe(el);

  onUnmounted(() => {
    cancelAnimationFrame(raf);
    ro.disconnect();
    window.removeEventListener("mousemove", onMove);
    renderer?.dispose();
    draco.dispose();
  });
});
</script>

<template>
  <div ref="host" class="viewer" title="戳我看今日塔罗" />
</template>

<style scoped>
.viewer {
  width: 100%;
  height: 100%;
  cursor: pointer;
}
</style>
