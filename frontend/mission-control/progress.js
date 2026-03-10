export function countCompletedSteps(doneMap) {
  return Object.values(doneMap).filter(Boolean).length;
}

export function getPhaseProgress(phase, doneMap) {
  const completed = phase.steps.filter((step) => doneMap[step.id]).length;
  const total = phase.steps.length;
  return {
    completed,
    total,
    pct: total > 0 ? Math.round((completed / total) * 100) : 0,
  };
}
