import { AdaptiveDpr, PerformanceMonitor } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import { Bloom, EffectComposer, Vignette } from "@react-three/postprocessing";
import { Suspense, useEffect, useState } from "react";
import { useJarvis } from "./lib/store";
import { CameraRig } from "./scene/CameraRig";
import { Core } from "./scene/Core";
import { Universe } from "./scene/Galaxy";
import { Planets } from "./scene/Planets";
import { ApprovalCard } from "./ui/Approval";
import { Conversation } from "./ui/Conversation";
import { TopBar } from "./ui/TopBar";
import { SidePanels } from "./ui/SidePanels";
import { PlanetPanel } from "./ui/PlanetPanel";
import { useShortcuts } from "./ui/shortcuts";

export default function App() {
  const settingQuality = useJarvis((s) => s.settings.graphics_quality) as "high" | "low" | undefined;
  const hidden = useHidden();
  const [autoLow, setAutoLow] = useState(false); // drop quality automatically if the GPU struggles
  const quality = settingQuality === "low" || autoLow ? "low" : "high";
  const focus = useJarvis((s) => s.focus);
  useShortcuts();

  return (
    <div className="fixed inset-0 fade-in">
      <Canvas frameloop={hidden ? "never" : "always"} camera={{ fov: 55, near: 0.1, far: 1200, position: [0, 30, 70] }} dpr={[1, quality === "high" ? 1.5 : 1]}
        gl={{ antialias: false, powerPreference: "high-performance" }}
        onPointerMissed={() => useJarvis.getState().setHover(null)}>
        <color attach="background" args={["#010208"]} />
        <PerformanceMonitor onDecline={() => setAutoLow(true)} />
        <AdaptiveDpr pixelated={false} />
        <ambientLight intensity={0.05} />
        <Suspense fallback={null}>
          <Universe quality={quality} />
          <Core />
          <Planets />
        </Suspense>
        <CameraRig />
        {quality === "high" && (<EffectComposer multisampling={0}>
          <Bloom intensity={1.1} luminanceThreshold={0.18} luminanceSmoothing={0.4} mipmapBlur />
          <Vignette eskil={false} offset={0.25} darkness={0.75} />
        </EffectComposer>)}
      </Canvas>
      <TopBar />
      {!focus && <SidePanels />}
      <Conversation />
      <PlanetPanel />
      <ApprovalCard />
    </div>
  );
}

// Stop rendering the 3D scene while the window is minimised or hidden, so the CPU/GPU stay free for voice + AI.
function useHidden() {
  const [hidden, setHidden] = useState(document.hidden);
  useEffect(() => {
    const on = () => setHidden(document.hidden);
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  return hidden;
}
