"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

export default function StlPreview({ url, token }: { url: string; token: string }) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    const container = host.current;
    if (!container) return;
    let disposed = false;
    const width = Math.max(container.clientWidth, 320);
    const height = 390;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x121820);
    const camera = new THREE.PerspectiveCamera(35, width / height, 0.1, 10_000);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    container.replaceChildren(renderer.domElement);
    scene.add(new THREE.HemisphereLight(0xd8efff, 0x17202a, 2.5));
    const key = new THREE.DirectionalLight(0xffffff, 3);
    key.position.set(2, 3, 4);
    scene.add(key);
    const grid = new THREE.GridHelper(100, 20, 0x334659, 0x24313e);
    scene.add(grid);

    let mesh: THREE.Mesh | undefined;
    let frame = 0;
    const pointer = { x: 0.7, y: 0.45 };
    const onPointer = (event: PointerEvent) => {
      const bounds = renderer.domElement.getBoundingClientRect();
      pointer.x = (event.clientX - bounds.left) / bounds.width;
      pointer.y = (event.clientY - bounds.top) / bounds.height;
    };
    renderer.domElement.addEventListener("pointermove", onPointer);

    fetch(url, { headers: { "x-manual-api-token": token } })
      .then(async (response) => {
        if (!response.ok) throw new Error(`Не удалось загрузить STL (${response.status}).`);
        return response.arrayBuffer();
      })
      .then((buffer) => {
        if (disposed) return;
        const geometry = new STLLoader().parse(buffer);
        geometry.computeVertexNormals();
        geometry.center();
        geometry.computeBoundingBox();
        const bounds = geometry.boundingBox ?? new THREE.Box3();
        const size = bounds.getSize(new THREE.Vector3());
        const span = Math.max(size.x, size.y, size.z);
        mesh = new THREE.Mesh(
          geometry,
          new THREE.MeshStandardMaterial({
            color: 0x72e3b5,
            roughness: 0.38,
            metalness: 0.2,
          }),
        );
        mesh.rotation.x = -Math.PI / 2;
        mesh.position.y = size.z / 2;
        scene.add(mesh);
        camera.position.set(span * 1.35, span * 1.1, span * 1.45);
        camera.lookAt(0, 0, 0);
        grid.scale.setScalar(Math.max(span / 40, 0.5));
      })
      .catch((reason: unknown) => {
        if (!disposed) setError(reason instanceof Error ? reason.message : "Ошибка 3D‑превью.");
      });

    const animate = () => {
      if (disposed) return;
      frame = requestAnimationFrame(animate);
      if (mesh) {
        mesh.rotation.z += ((pointer.x - 0.5) * Math.PI * 0.7 - mesh.rotation.z) * 0.035;
        mesh.rotation.x += (-Math.PI / 2 + (pointer.y - 0.5) * 0.4 - mesh.rotation.x) * 0.035;
      }
      renderer.render(scene, camera);
    };
    animate();
    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      renderer.domElement.removeEventListener("pointermove", onPointer);
      mesh?.geometry.dispose();
      (mesh?.material as THREE.Material | undefined)?.dispose();
      renderer.dispose();
      container.replaceChildren();
    };
  }, [token, url]);

  return (
    <div className="preview">
      <div ref={host} className="preview-canvas" />
      {error && <p className="error">{error}</p>}
      <small>Двигайте курсор над моделью, чтобы осмотреть её.</small>
    </div>
  );
}
