import { useEffect, useRef, useState } from "react";
import PhaseCompletionBanner from "./components/PhaseCompletionBanner";
import PhaseHeader from "./components/PhaseHeader";
import Sidebar from "./components/Sidebar";
import StepCard from "./components/StepCard";
import { C, PHASES, TOTAL_STEPS } from "./data/missionControlData";
import { countCompletedSteps, getPhaseProgress } from "./progress";
import { loadMissionProgress, saveMissionProgress } from "./storage";

export default function MissionControlApp() {
  const [doneMap, setDoneMap] = useState({});
  const [activePhaseIndex, setActivePhaseIndex] = useState(0);
  const [openStepId, setOpenStepId] = useState(null);
  const [copiedStepId, setCopiedStepId] = useState(null);
  const topRef = useRef(null);

  useEffect(() => {
    let mounted = true;

    async function loadProgress() {
      const savedProgress = await loadMissionProgress();
      if (mounted) {
        setDoneMap(savedProgress);
      }
    }

    loadProgress();

    return () => {
      mounted = false;
    };
  }, []);

  function scrollToTop() {
    topRef.current?.scrollTo(0, 0);
  }

  function setPhase(nextPhaseIndex) {
    setActivePhaseIndex(nextPhaseIndex);
  }

  function markDone(stepId) {
    setDoneMap((currentDoneMap) => {
      const nextDoneMap = { ...currentDoneMap, [stepId]: !currentDoneMap[stepId] };
      saveMissionProgress(nextDoneMap);
      return nextDoneMap;
    });
  }

  async function copyToClipboard(text, stepId) {
    try {
      await navigator.clipboard.writeText(text);
    } catch {}

    setCopiedStepId(stepId);
    setTimeout(() => setCopiedStepId(null), 2000);
  }

  const currentPhase = PHASES[activePhaseIndex];
  const doneCount = countCompletedSteps(doneMap);
  const currentPhaseProgress = getPhaseProgress(currentPhase, doneMap);

  return (
    <div
      style={{
        display: "flex",
        height: "100vh",
        background: C.bg,
        color: C.textPrimary,
        fontFamily: "'Courier New',monospace",
        fontSize: 12,
        overflow: "hidden",
      }}
    >
      <Sidebar
        activePhaseIndex={activePhaseIndex}
        doneCount={doneCount}
        doneMap={doneMap}
        phases={PHASES}
        scrollToTop={scrollToTop}
        setActivePhaseIndex={setPhase}
        setOpenStepId={setOpenStepId}
        totalSteps={TOTAL_STEPS}
      />

      <div ref={topRef} style={{ flex: 1, overflowY: "auto", padding: "20px 24px 60px" }}>
        <PhaseHeader
          activePhaseIndex={activePhaseIndex}
          onNextPhase={() => setPhase(Math.min(PHASES.length - 1, activePhaseIndex + 1))}
          onPreviousPhase={() => setPhase(Math.max(0, activePhaseIndex - 1))}
          phase={currentPhase}
          phases={PHASES}
          scrollToTop={scrollToTop}
        />

        {currentPhase.steps.map((step, stepIndex) => (
          <StepCard
            key={step.id}
            copiedStepId={copiedStepId}
            currentPhase={currentPhase}
            isDone={Boolean(doneMap[step.id])}
            isOpen={openStepId === step.id}
            markDone={markDone}
            onCopy={copyToClipboard}
            onOpenNextStep={() => setOpenStepId(currentPhase.steps[stepIndex + 1].id)}
            setOpenStepId={setOpenStepId}
            step={step}
            stepIndex={stepIndex}
          />
        ))}

        <PhaseCompletionBanner
          activePhaseIndex={activePhaseIndex}
          onAdvance={() => setPhase(activePhaseIndex + 1)}
          phase={currentPhase}
          phases={PHASES}
          progress={currentPhaseProgress}
          scrollToTop={scrollToTop}
          setOpenStepId={setOpenStepId}
        />
      </div>
    </div>
  );
}
