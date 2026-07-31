// ─────────────────────────────────────────────────────────────
//  FASE 4 — Agente revisor con IA REAL (provider-agnóstico)
// ─────────────────────────────────────────────────────────────
// Compara la DESCRIPCIÓN del PR contra el DIFF y decide si el
// código coincide con lo prometido (detecta 'scope creep').
//
// Usa el SDK de OpenAI, pero TODO es configurable por entorno para
// poder migrar sin reescribir código:
//   LLM_API_KEY   -> credencial (hoy tu OPENAI_API_KEY; en la oficina
//                    podría ser el GITHUB_TOKEN con GitHub Models).
//   LLM_BASE_URL  -> endpoint. Vacío = OpenAI. Para GitHub Models /
//                    Azure OpenAI, apúntalo a su URL (compatible OpenAI).
//   LLM_MODEL     -> nombre del modelo (por defecto: gpt-4o-mini).
//
// Si NO hay credencial, cae a un motor MOCK para que el lab siga
// funcionando. La salida (JSON) mantiene el contrato de la Fase 3.

import { readFileSync } from "node:fs";
import OpenAI from "openai";

const SCHEMA_VERSION = "1.0";
const MAX_DIFF_CHARS = 60000; // límite para no disparar el consumo de tokens
const DEFAULT_MODEL = "gpt-4o-mini";

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

function truncate(text, max) {
  if (text.length <= max) return { text, truncated: false };
  return { text: text.slice(0, max), truncated: true };
}

// Asegura que la respuesta del modelo respete nuestro contrato.
function normalizeResult(r) {
  const valid = ["approve", "request_changes", "comment"];
  return {
    verdict: valid.includes(r?.verdict) ? r.verdict : "comment",
    aligned: Boolean(r?.aligned),
    confidence: typeof r?.confidence === "number" ? r.confidence : null,
    summary: typeof r?.summary === "string" ? r.summary : "",
    issues: Array.isArray(r?.issues) ? r.issues : [],
  };
}

// ── Motor MOCK (respaldo si no hay credenciales) ───────────────
function evaluateMock(input) {
  const issues = [];
  if (input.description.length < 15) {
    issues.push({
      type: "missing_description",
      severity: "high",
      message:
        "La descripción del PR está vacía o es demasiado corta para verificar el código.",
      files: [],
    });
  }
  const aligned = issues.length === 0;
  return {
    engine: "mock",
    verdict: aligned ? "approve" : "request_changes",
    aligned,
    confidence: 0.5,
    summary: aligned
      ? "Verificación superficial superada (motor mock, sin IA)."
      : "Se encontraron observaciones (motor mock, sin IA).",
    issues,
  };
}

// ── Motor IA (endpoint compatible con OpenAI) ──────────────────
async function evaluateWithLLM(input, { apiKey, baseURL, model }) {
  const client = new OpenAI({ apiKey, baseURL: baseURL || undefined });
  const { text: diff, truncated } = truncate(input.diff, MAX_DIFF_CHARS);

  const system = [
    "Eres un revisor automático de Pull Requests.",
    "Tarea: verificar si la DESCRIPCIÓN del PR coincide con los cambios reales del DIFF.",
    "Reglas:",
    "- El código debe hacer lo que promete la descripción, y NADA más.",
    "- Marca 'scope creep': cambios del diff que la descripción NO menciona.",
    "- Marca también lo prometido en la descripción que NO aparece en el diff.",
    "- Sé estricto pero justo. No inventes cambios que no estén en el diff.",
    "Responde EXCLUSIVAMENTE en formato JSON con este esquema:",
    '{ "verdict": "approve"|"request_changes"|"comment", "aligned": boolean,',
    '  "confidence": number(0..1), "summary": string(en español),',
    '  "issues": [ { "type": string, "severity": "low"|"medium"|"high",',
    '               "message": string, "files": string[] } ] }',
  ].join("\n");

  const user = [
    `Repositorio: ${input.repo}`,
    `PR #${input.prNumber}`,
    `Título: ${input.title}`,
    "",
    "DESCRIPCIÓN DEL PR:",
    input.description || "(sin descripción)",
    "",
    `ARCHIVOS CAMBIADOS (${input.changedFiles.length}):`,
    input.changedFiles.join("\n") || "(ninguno)",
    "",
    `DIFF${truncated ? " (TRUNCADO)" : ""}:`,
    diff || "(vacío)",
  ].join("\n");

  const resp = await client.chat.completions.create({
    model,
    temperature: 0,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: system },
      { role: "user", content: user },
    ],
  });

  const raw = resp.choices?.[0]?.message?.content || "{}";
  return { engine: "llm", ...normalizeResult(JSON.parse(raw)) };
}

async function evaluate(input) {
  const apiKey = process.env.LLM_API_KEY || process.env.OPENAI_API_KEY;
  const baseURL = process.env.LLM_BASE_URL || "";
  const model = process.env.LLM_MODEL || DEFAULT_MODEL;

  if (!apiKey) return evaluateMock(input);

  try {
    return await evaluateWithLLM(input, { apiKey, baseURL, model });
  } catch (err) {
    // No tumbamos el workflow: devolvemos un veredicto válido que
    // deja claro que la IA no pudo ejecutarse.
    return {
      engine: "error",
      verdict: "comment",
      aligned: false,
      confidence: null,
      summary: `El agente de IA no pudo completar la revisión: ${err.message}`,
      issues: [
        { type: "agent_error", severity: "high", message: String(err.message), files: [] },
      ],
    };
  }
}

async function main() {
  const input = gatherInput();
  const result = await evaluate(input);
  const model = process.env.LLM_MODEL || DEFAULT_MODEL;

  const output = {
    schema_version: SCHEMA_VERSION,
    verdict: result.verdict, // approve | request_changes | comment
    aligned: result.aligned,
    confidence: result.confidence,
    summary: result.summary,
    issues: result.issues,
    metadata: {
      repo: input.repo,
      pr_number: input.prNumber,
      changed_files: input.changedFiles.length,
      additions: input.additions,
      deletions: input.deletions,
      engine: result.engine, // llm | mock | error
      model: result.engine === "llm" ? model : null,
      generated_at: new Date().toISOString(),
    },
  };

  process.stdout.write(JSON.stringify(output, null, 2) + "\n");
}

main();
