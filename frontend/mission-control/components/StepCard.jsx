import { C, TYPE_COLOR, TYPE_LABEL } from "../data/missionControlData";

export default function StepCard({
  copiedStepId,
  currentPhase,
  isDone,
  isOpen,
  markDone,
  onCopy,
  onOpenNextStep,
  setOpenStepId,
  step,
  stepIndex,
}) {
  const typeColor = TYPE_COLOR[step.type] || C.textSec;

  return (
    <div
      style={{
        marginBottom: 8,
        border: `1px solid ${
          isDone ? "#00ff8840" : isOpen ? C.borderBright : C.border
        }`,
        borderRadius: 4,
        background: isDone ? "rgba(0,255,136,0.03)" : isOpen ? C.card : C.panel,
      }}
    >
      <div
        onClick={() => setOpenStepId(isOpen ? null : step.id)}
        style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 14px", cursor: "pointer" }}
      >
        <div
          onClick={(event) => {
            event.stopPropagation();
            markDone(step.id);
          }}
          style={{
            width: 18,
            height: 18,
            borderRadius: "50%",
            flexShrink: 0,
            border: `2px solid ${isDone ? C.green : C.borderBright}`,
            background: isDone ? "rgba(0,255,136,0.2)" : "transparent",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            cursor: "pointer",
            fontSize: 9,
            color: C.green,
          }}
        >
          {isDone ? "✓" : ""}
        </div>

        <span
          style={{
            fontSize: 8,
            padding: "1px 5px",
            borderRadius: 2,
            border: `1px solid ${typeColor}50`,
            color: typeColor,
            flexShrink: 0,
          }}
        >
          {TYPE_LABEL[step.type]}
        </span>
        <span style={{ fontSize: 8, color: C.textDim, flexShrink: 0 }}>{step.id}</span>
        <span
          style={{
            flex: 1,
            fontSize: 11,
            color: isDone ? C.textPrimary : C.textSec,
            fontWeight: isDone ? "bold" : "normal",
          }}
        >
          {step.title}
        </span>
        <span style={{ color: C.textDim, fontSize: 11 }}>{isOpen ? "▲" : "▼"}</span>
      </div>

      {isOpen ? (
        <div style={{ padding: "0 14px 14px", borderTop: `1px solid ${C.border}` }}>
          <div style={{ marginTop: 10, fontSize: 11, color: C.textSec, lineHeight: 1.7 }}>
            {step.desc}
          </div>

          {step.warn ? (
            <div
              style={{
                marginTop: 8,
                padding: "7px 10px",
                background: "rgba(255,107,53,0.08)",
                borderLeft: `3px solid ${C.orange}`,
                border: `1px solid rgba(255,107,53,0.25)`,
                borderRadius: 3,
                fontSize: 10,
                color: C.orange,
                lineHeight: 1.6,
              }}
            >
              ⚠ {step.warn}
            </div>
          ) : null}

          {step.cmd ? (
            <div style={{ marginTop: 10 }}>
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  marginBottom: 5,
                }}
              >
                <span style={{ fontSize: 8, color: typeColor, letterSpacing: 2 }}>
                  {step.type === "prompt"
                    ? "COPY → PASTE INTO ANTIGRAVITY IDE"
                    : step.type === "cmd"
                      ? "RUN IN TERMINAL (copy whole block)"
                      : "CREATE THIS FILE"}
                </span>
                <button
                  onClick={() => onCopy(step.cmd, step.id)}
                  style={{
                    padding: "3px 10px",
                    fontSize: 8,
                    fontFamily: "inherit",
                    background: copiedStepId === step.id ? "rgba(0,255,136,0.15)" : `${typeColor}10`,
                    border: `1px solid ${copiedStepId === step.id ? C.green : typeColor}60`,
                    color: copiedStepId === step.id ? C.green : typeColor,
                    cursor: "pointer",
                    borderRadius: 2,
                    letterSpacing: 1,
                  }}
                >
                  {copiedStepId === step.id ? "✓ COPIED" : "COPY"}
                </button>
              </div>
              <pre
                style={{
                  margin: 0,
                  padding: 12,
                  fontSize: 10,
                  lineHeight: 1.7,
                  background: step.type === "prompt" ? "#080d18" : "#050e1a",
                  border: `1px solid ${typeColor}25`,
                  borderRadius: 3,
                  color: step.type === "prompt" ? "#c4a8ff" : "#8ecf8e",
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  maxHeight: 360,
                  overflowY: "auto",
                }}
              >
                {step.cmd}
              </pre>
            </div>
          ) : null}

          {step.verify ? (
            <div
              style={{
                marginTop: 8,
                padding: "8px 10px",
                background: `${typeColor}06`,
                borderLeft: `3px solid ${typeColor}`,
                border: `1px solid ${typeColor}20`,
                borderRadius: 3,
              }}
            >
              <div style={{ fontSize: 8, color: typeColor, letterSpacing: 2, marginBottom: 4 }}>
                {step.type === "action" ? "HOW TO DO IT" : "EXPECTED OUTPUT / HOW TO VERIFY"}
              </div>
              <pre
                style={{
                  margin: 0,
                  fontSize: 10,
                  color: C.textSec,
                  whiteSpace: "pre-wrap",
                  lineHeight: 1.6,
                }}
              >
                {step.verify}
              </pre>
            </div>
          ) : null}

          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <button
              onClick={() => markDone(step.id)}
              style={{
                padding: "6px 16px",
                fontSize: 9,
                fontFamily: "inherit",
                background: isDone ? "rgba(0,255,136,0.12)" : `${currentPhase.color}15`,
                border: `1px solid ${isDone ? C.green : currentPhase.color}`,
                color: isDone ? C.green : currentPhase.color,
                cursor: "pointer",
                borderRadius: 2,
                letterSpacing: 1,
              }}
            >
              {isDone ? "✓ MARK INCOMPLETE" : "✓ MARK COMPLETE"}
            </button>
            {stepIndex < currentPhase.steps.length - 1 ? (
              <button
                onClick={onOpenNextStep}
                style={{
                  padding: "6px 14px",
                  fontSize: 9,
                  fontFamily: "inherit",
                  background: "transparent",
                  border: `1px solid ${C.border}`,
                  color: C.textDim,
                  cursor: "pointer",
                  borderRadius: 2,
                }}
              >
                NEXT STEP →
              </button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
