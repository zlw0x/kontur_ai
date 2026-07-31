"use client";

import { useEffect, useRef, useState } from "react";
import * as THREE from "three";
import { OrbitControls } from "three/examples/jsm/controls/OrbitControls.js";
import { STLLoader } from "three/examples/jsm/loaders/STLLoader.js";

type MaterialName = "aluminum" | "steel" | "polymer" | "cad";
type Dimensions = { length: number; width: number; height: number };

const materialPalette: Record<MaterialName, { color: number; metalness: number; roughness: number }> = {
  aluminum: { color: 0xe0e7e8, metalness: 0.42, roughness: 0.28 },
  steel: { color: 0xb9c4cd, metalness: 0.58, roughness: 0.22 },
  polymer: { color: 0xb6ec58, metalness: 0.08, roughness: 0.32 },
  cad: { color: 0xc4c8c7, metalness: 0.02, roughness: 0.68 },
};

export default function StlPreview({
  url,
  token,
  local = false,
  material = "aluminum",
  dimensions,
  ready = false,
  transparent = false,
}: {
  url?: string;
  token?: string;
  local?: boolean;
  material?: MaterialName;
  dimensions: Dimensions | null;
  ready?: boolean;
  transparent?: boolean;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");
  const [wireframe, setWireframe] = useState(false);
  const [resetKey, setResetKey] = useState(0);
  /**
   * Proportions for the stand-in shape only, never displayed as fact.
   *
   * `dimensions` is null until something has actually been measured. The chips
   * used to print whatever it held, so before a build a visitor was told their
   * drawing was 80 x 40 x 12 — numbers that came from the layout, not from any
   * model. The stand-in shape still needs a size to be drawn at; it just may not
   * claim one.
   */
  const layoutLength = dimensions?.length ?? 80;
  const layoutWidth = dimensions?.width ?? 40;
  const layoutHeight = dimensions?.height ?? 12;

  useEffect(() => {
    const container = host.current;
    if (!container) return;

    let disposed = false;
    let frame = 0;
    const scene = new THREE.Scene();
    if (!transparent) scene.fog = new THREE.FogExp2(0x111418, 0.0055);

    const camera = new THREE.PerspectiveCamera(31, 1, 0.1, 10_000);
    camera.position.set(105, 80, 112);

    const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = material === "cad" ? 1.02 : 1.28;
    renderer.setClearColor(0x000000, 0);
    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    container.replaceChildren(renderer.domElement);

    const controls = new OrbitControls(camera, renderer.domElement);
    controls.enableDamping = true;
    controls.dampingFactor = 0.065;
    controls.enablePan = true;
    controls.minDistance = 35;
    controls.maxDistance = 420;
    controls.autoRotate = true;
    controls.autoRotateSpeed = ready ? 0.42 : 0.28;
    controls.target.set(0, 2, 0);

    renderer.domElement.addEventListener("pointerdown", () => {
      controls.autoRotate = false;
    });

    scene.add(new THREE.HemisphereLight(0xf3fbff, 0x1b242a, 3.1));

    const key = new THREE.DirectionalLight(0xffffff, 6.2);
    key.position.set(70, 110, 90);
    key.castShadow = true;
    key.shadow.mapSize.set(2048, 2048);
    key.shadow.camera.left = -120;
    key.shadow.camera.right = 120;
    key.shadow.camera.top = 120;
    key.shadow.camera.bottom = -120;
    scene.add(key);

    const rim = new THREE.DirectionalLight(0x9dffcb, 3.2);
    rim.position.set(-90, 55, -65);
    scene.add(rim);

    const fill = new THREE.PointLight(0x8fa7ff, 2.8, 360);
    fill.position.set(80, 25, -90);
    scene.add(fill);

    const floor = new THREE.Mesh(
      new THREE.CircleGeometry(150, 96),
      new THREE.MeshStandardMaterial({
        color: 0x171b20,
        metalness: 0.04,
        roughness: 0.82,
        transparent: true,
        opacity: 0.88,
      }),
    );
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -layoutHeight / 2 - 1.2;
    floor.receiveShadow = true;
    if (!transparent) scene.add(floor);

    const grid = new THREE.GridHelper(260, 26, 0x46515c, 0x252b31);
    grid.position.y = floor.position.y + 0.04;
    const gridMaterials = Array.isArray(grid.material) ? grid.material : [grid.material];
    gridMaterials.forEach((gridMaterial) => {
      gridMaterial.transparent = true;
      gridMaterial.opacity = 0.28;
    });
    if (!transparent) scene.add(grid);

    const halo = new THREE.Mesh(
      new THREE.RingGeometry(62, 100, 96),
      new THREE.MeshBasicMaterial({
        color: ready ? 0x9eea63 : 0x64707d,
        transparent: true,
        opacity: ready ? 0.055 : 0.025,
        side: THREE.DoubleSide,
      }),
    );
    halo.rotation.x = -Math.PI / 2;
    halo.position.y = floor.position.y + 0.08;
    if (!transparent) scene.add(halo);

    const root = new THREE.Group();
    scene.add(root);
    const disposableGeometries: THREE.BufferGeometry[] = [floor.geometry, grid.geometry, halo.geometry];
    const disposableMaterials: THREE.Material[] = [
      floor.material as THREE.Material,
      ...gridMaterials,
      halo.material as THREE.Material,
    ];

    const palette = materialPalette[material];
    const modelMaterial = new THREE.MeshPhysicalMaterial({
      color: palette.color,
      metalness: palette.metalness,
      roughness: palette.roughness,
      clearcoat: material === "polymer" ? 0.55 : material === "cad" ? 0.02 : 0.18,
      clearcoatRoughness: 0.23,
      wireframe,
      transparent: !ready,
      opacity: ready ? 1 : 0.86,
    });
    disposableMaterials.push(modelMaterial);

    const addMesh = (geometry: THREE.BufferGeometry, edgeOpacity = 0.58) => {
      geometry.computeVertexNormals();
      const mesh = new THREE.Mesh(geometry, modelMaterial);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      root.add(mesh);
      disposableGeometries.push(geometry);

      if (!wireframe) {
        const edgeGeometry = new THREE.EdgesGeometry(geometry, 24);
        const edgeMaterial = new THREE.LineBasicMaterial({
          color: material === "polymer" ? 0x28321c : material === "cad" ? 0x596160 : 0x263139,
          transparent: true,
          opacity: edgeOpacity,
        });
        const edges = new THREE.LineSegments(edgeGeometry, edgeMaterial);
        root.add(edges);
        disposableGeometries.push(edgeGeometry);
        disposableMaterials.push(edgeMaterial);
      }
      return mesh;
    };

    const frameModel = (span: number) => {
      const distance = Math.max(span * 1.72, 82);
      camera.position.set(distance * 0.88, distance * 0.68, distance);
      camera.near = Math.max(distance / 1000, 0.1);
      camera.far = distance * 20;
      camera.updateProjectionMatrix();
      controls.minDistance = Math.max(span * 0.62, 26);
      controls.maxDistance = Math.max(span * 6, 260);
      controls.target.set(0, Math.max(layoutHeight * 0.12, 1), 0);
      controls.update();
    };

    const buildProceduralModel = () => {
      // A stand-in so the stage is not empty before a build. It is not the
      // visitor's part, so the chips above stay empty while it is on screen.
      const length = clamp(layoutLength, 50, 130);
      const width = clamp(layoutWidth, 28, 80);
      const height = clamp(layoutHeight, 7, 28);
      const cornerRadius = Math.min(width * 0.16, 8);
      const plate = roundedRectangle(length, width, cornerRadius);
      const holeRadius = 4;
      const holeX = length / 2 - 10;
      const holeY = width / 2 - 8;

      for (const x of [-holeX, holeX]) {
        for (const y of [-holeY, holeY]) {
          const hole = new THREE.Path();
          hole.absarc(x, y, holeRadius, 0, Math.PI * 2, true);
          plate.holes.push(hole);
        }
      }

      const baseGeometry = new THREE.ExtrudeGeometry(plate, {
        depth: height,
        bevelEnabled: true,
        bevelSegments: 3,
        bevelSize: Math.min(height * 0.065, 0.75),
        bevelThickness: Math.min(height * 0.065, 0.75),
        curveSegments: 48,
      });
      baseGeometry.translate(0, 0, -height / 2);
      addMesh(baseGeometry);

      const bossOuter = Math.min(width * 0.29, 11.6);
      const bossInner = 4;
      const boss = new THREE.Shape();
      boss.absarc(0, 0, bossOuter, 0, Math.PI * 2, false);
      const bossHole = new THREE.Path();
      bossHole.absarc(0, 0, bossInner, 0, Math.PI * 2, true);
      boss.holes.push(bossHole);
      const bossHeight = Math.max(height * 0.65, 6);
      const bossGeometry = new THREE.ExtrudeGeometry(boss, {
        depth: bossHeight,
        bevelEnabled: true,
        bevelSegments: 3,
        bevelSize: 0.65,
        bevelThickness: 0.65,
        curveSegments: 64,
      });
      bossGeometry.translate(0, 0, height / 2 - 0.25);
      addMesh(bossGeometry, 0.48);

      root.rotation.x = -Math.PI / 2;
      root.rotation.z = -0.05;
      frameModel(Math.max(length, width, height + bossHeight));
    };

    const loadModel = async () => {
      if (!url || local) {
        buildProceduralModel();
        return;
      }
      const response = await fetch(url, {
        headers: token ? { "x-manual-api-token": token } : undefined,
      });
      if (!response.ok) throw new Error("Не удалось открыть 3D-модель.");
      const geometry = new STLLoader().parse(await response.arrayBuffer());
      geometry.center();
      geometry.computeBoundingBox();
      const bounds = geometry.boundingBox ?? new THREE.Box3();
      const size = bounds.getSize(new THREE.Vector3());
      const mesh = addMesh(geometry);
      mesh.rotation.x = -Math.PI / 2;
      mesh.position.y = size.z / 2;
      frameModel(Math.max(size.x, size.y, size.z));
    };

    void loadModel().catch((reason: unknown) => {
      if (!disposed) setError(reason instanceof Error ? reason.message : "Не удалось открыть модель.");
    });

    const resize = () => {
      const width = Math.max(container.clientWidth, 320);
      const height = Math.max(container.clientHeight, transparent ? 170 : 420);
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      camera.updateProjectionMatrix();
    };
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);
    resize();

    const animate = () => {
      if (disposed) return;
      frame = requestAnimationFrame(animate);
      controls.update();
      renderer.render(scene, camera);
    };
    animate();

    return () => {
      disposed = true;
      cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      controls.dispose();
      disposableGeometries.forEach((geometry) => geometry.dispose());
      disposableMaterials.forEach((materialItem) => materialItem.dispose());
      renderer.dispose();
      container.replaceChildren();
    };
  }, [layoutHeight, layoutLength, layoutWidth, local, material, ready, resetKey, token, transparent, url, wireframe]);

  function toggleFullscreen() {
    const element = host.current?.parentElement;
    if (!element) return;
    if (document.fullscreenElement) {
      void document.exitFullscreen();
    } else {
      void element.requestFullscreen();
    }
  }

  return (
    <div className={`preview${transparent ? " preview-transparent" : ""}`}>
      <div ref={host} className="preview-canvas" />
      <div className="preview-tools" aria-label="Управление видом">
        <button type="button" onClick={() => setResetKey((value) => value + 1)} title="Исходный вид">
          <svg viewBox="0 0 24 24"><path d="M4 11a8 8 0 1 1 2.3 6M4 5v6h6" /></svg>
        </button>
        <button
          type="button"
          className={wireframe ? "active" : ""}
          onClick={() => setWireframe((value) => !value)}
          title="Каркас"
        >
          <svg viewBox="0 0 24 24"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9L12 3Zm-7.6 4.7L12 12l7.6-4.3M12 12v9" /></svg>
        </button>
        <button type="button" onClick={toggleFullscreen} title="На весь экран">
          <svg viewBox="0 0 24 24"><path d="M9 4H4v5m11-5h5v5M9 20H4v-5m11 5h5v-5" /></svg>
        </button>
      </div>
      <div className="axis-gizmo" aria-hidden="true">
        <span className="axis-z">Z</span>
        <span className="axis-y">Y</span>
        <span className="axis-x">X</span>
        <i />
      </div>
      {dimensions && (
        <div className="dimension-chips">
          <span><i>L</i>{dimensions.length} мм</span>
          <span><i>W</i>{dimensions.width} мм</span>
          <span><i>H</i>{dimensions.height} мм</span>
        </div>
      )}
      <div className="preview-hint">Вращайте · Приближайте · Перемещайте</div>
      {error && <p className="preview-error">{error}</p>}
    </div>
  );
}

function roundedRectangle(width: number, height: number, radius: number) {
  const x = -width / 2;
  const y = -height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius);
  shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height);
  shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  return shape;
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(Math.max(value, minimum), maximum);
}
