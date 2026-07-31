// ─────────────────────────────────────────────────────────────
//  FASE 3 — Agente revisor (MOCK, sin IA todavía)
// ─────────────────────────────────────────────────────────────
// Recibe los datos del PR (repo, título, descripción, diff, archivos)
// y devuelve un VEREDICTO en JSON con un CONTRATO fijo.
//
// Aún NO usa IA: aplica una heurística simple. En la Fase 4
// reemplazaremos únicamente la función evaluate() por una llamada
// real al modelo, manteniendo EXACTAMENTE este formato de salida.
//
// Entradas (por variables de entorno y archivos):
//   PR_REPO, PR_NUMBER, PR_TITLE, PR_BODY, PR_AUTHOR,
//   PR_ADDITIONS, PR_DELETIONS
//   DIFF_FILE   -> ruta al diff completo   (por defecto: pr.diff)
//   FILES_FILE  -> ruta a la lista de files (por defecto: changed_files.txt)
//
// Salida: JSON por stdout (para que otros pasos lo consuman).

import { readFileSync } from "node:fs";

const SCHEMA_VERSION = "1.0";

function readFileSafe(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return "";
  }
}

function gatherInput() {
  const diff = readFileSafe(process.env.DIFF_FILE || "pr.diff");
  const changedFiles = readFileSafe(process.env.FILES_FILE || "changed_files.txt")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  return {
    repo: process.env.PR_REPO || "",
    prNumber: Number(process.env.PR_NUMBER || 0),
    title: process.env.PR_TITLE || "",
    description: (process.env.PR_BODY || "").trim(),
    author: process.env.PR_AUTHOR || "",
    additions: Number(process.env.PR_ADDITIONS || 0),
    deletions: Number(process.env.PR_DELETIONS || 0),
    changedFiles,
    diff,
  };
}

// ── Evaluación MOCK (se reemplazará por IA en la Fase 4) ────────
function evaluate(input) {
  const issues = [];

  // Heurística de demostración: sin descripción no se puede verificar
  // que el código coincida con lo prometido.
  if (input.description.length < 15) {
    issues.push({
      type: "missing_description",
      severity: "high",
      message:
        "La descripción del PR está vacía o es demasiado corta para verificar que el código coincide con lo descrito.",
      files: [],
    });
  }

  // NOTA: aquí, en la Fase 4, la IA comparará la descripción contra el
  // diff para detectar 'scope creep' (cambios no descritos por el dev).

  const aligned = issues.length === 0;

  return {
    aligned,
    verdict: aligned ? "approve" : "request_changes",
    confidence: 0.5, // mock: sin IA no hay confianza real
    summary: aligned
      ? "Verificación superficial superada (motor mock, sin IA)."
      : "Se encontraron observaciones que impiden aprobar automáticamente.",
    issues,
  };
}

function main() {
  const input = gatherInput();
  const result = evaluate(input);

  const output = {
    schema_version: SCHEMA_VERSION,
    verdict: result.verdict, // approve | request_changes | comment
    aligned: result.aligned, // ¿el código concuerda con lo descrito?
    confidence: result.confidence, // 0..1
    summary: result.summary,
    issues: result.issues,
    metadata: {
      repo: input.repo,
      pr_number: input.prNumber,
      changed_files: input.changedFiles.length,
      additions: input.additions,
      deletions: input.deletions,
      engine: "mock",
      generated_at: new Date().toISOString(),
    },
  };

  process.stdout.write(JSON.stringify(output, null, 2) + "\n");
}

main();
