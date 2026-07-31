// ─────────────────────────────────────────────────────────────
//  FASE 4 — Agente revisor con IA REAL (agnóstico de proveedor)
// ─────────────────────────────────────────────────────────────
// Compara la DESCRIPCIÓN del PR contra el DIFF y decide si el
// código coincide con lo prometido (detecta 'invasión de alcance').
//
// Usa el SDK de OpenAI, pero TODO es configurable por entorno para
// poder migrar sin reescribir código:
//   IA_CLAVE_API -> credencial (hoy tu clave de OpenAI; en la oficina
//                   podría ser el GITHUB_TOKEN con GitHub Models).
//   IA_URL_BASE  -> endpoint. Vacío = OpenAI. Para GitHub Models /
//                   Azure OpenAI, apúntalo a su URL (compatible OpenAI).
//   IA_MODELO    -> nombre del modelo (por defecto: gpt-4o-mini).
//
// Si NO hay credencial, cae a un motor SIMULADO para no romper el flujo.

import { readFileSync } from "node:fs";
import OpenAI from "openai";

const VERSION_ESQUEMA = "1.0";
const MAX_CARACTERES_DIFF = 60000; // límite para no disparar el consumo de tokens
const MODELO_POR_DEFECTO = "gpt-4o-mini";

function leerArchivoSeguro(ruta) {
  try {
    return readFileSync(ruta, "utf8");
  } catch {
    return "";
  }
}

function recopilarEntrada() {
  const diff = leerArchivoSeguro(process.env.ARCHIVO_DIFF || "pr.diff");
  const archivosCambiados = leerArchivoSeguro(process.env.ARCHIVO_LISTA || "archivos_cambiados.txt")
    .split("\n")
    .map((linea) => linea.trim())
    .filter(Boolean);

  return {
    repositorio: process.env.PR_REPOSITORIO || "",
    numeroPr: Number(process.env.PR_NUMERO || 0),
    titulo: process.env.PR_TITULO || "",
    descripcion: (process.env.PR_DESCRIPCION || "").trim(),
    autor: process.env.PR_AUTOR || "",
    adiciones: Number(process.env.PR_ADICIONES || 0),
    eliminaciones: Number(process.env.PR_ELIMINACIONES || 0),
    archivosCambiados,
    diff,
  };
}

function truncar(texto, maximo) {
  if (texto.length <= maximo) return { texto, truncado: false };
  return { texto: texto.slice(0, maximo), truncado: true };
}

// Asegura que la respuesta del modelo respete nuestro contrato.
function normalizarResultado(r) {
  const validos = ["aprobado", "cambios_requeridos", "comentario"];
  return {
    veredicto: validos.includes(r?.veredicto) ? r.veredicto : "comentario",
    alineado: Boolean(r?.alineado),
    confianza: typeof r?.confianza === "number" ? r.confianza : null,
    resumen: typeof r?.resumen === "string" ? r.resumen : "",
    hallazgos: Array.isArray(r?.hallazgos) ? r.hallazgos : [],
  };
}

// ── Motor SIMULADO (respaldo si no hay credenciales) ───────────
function evaluarSimulado(entrada) {
  const hallazgos = [];
  if (entrada.descripcion.length < 15) {
    hallazgos.push({
      tipo: "descripcion_faltante",
      severidad: "alta",
      mensaje:
        "La descripción del PR está vacía o es demasiado corta para verificar el código.",
      archivos: [],
    });
  }
  const alineado = hallazgos.length === 0;
  return {
    motor: "simulado",
    veredicto: alineado ? "aprobado" : "cambios_requeridos",
    alineado,
    confianza: 0.5,
    resumen: alineado
      ? "Verificación superficial superada (motor simulado, sin IA)."
      : "Se encontraron observaciones (motor simulado, sin IA).",
    hallazgos,
  };
}

// ── Motor IA (endpoint compatible con OpenAI) ──────────────────
async function evaluarConIA(entrada, { claveApi, urlBase, modelo }) {
  const cliente = new OpenAI({ apiKey: claveApi, baseURL: urlBase || undefined });
  const { texto: diff, truncado } = truncar(entrada.diff, MAX_CARACTERES_DIFF);

  const sistema = [
    "Eres un revisor automático de Pull Requests. Evalúas si el CONJUNTO de",
    "cambios del DIFF se corresponde con la INTENCIÓN descrita en el PR, sin",
    "funcionalidad extra relevante que no haya sido descrita.",
    "",
    "Criterios (juzga por intención, no por literalidad):",
    "- La descripción resume el objetivo; NO exijas que enumere cada archivo",
    "  ni cada detalle de implementación.",
    "- NO es 'invasion_alcance' los cambios de soporte que acompañan de forma",
    "  natural a lo descrito: documentación/README, comentarios, configuración,",
    "  manifiestos de dependencias (p. ej. package.json), archivos de CI/workflow,",
    "  pruebas y refactorizaciones menores ligadas al objetivo.",
    "- SÍ es 'invasion_alcance' la funcionalidad NUEVA no relacionada, los cambios",
    "  de comportamiento no descritos, o modificaciones a módulos ajenos al objetivo.",
    "- Reporta 'cambios_faltantes' solo si la descripción promete algo FUNCIONAL",
    "  que no aparece en el diff (no por omitir detalles de implementación).",
    "- Severidad 'alta' solo para desalineaciones sustanciales; usa 'baja'/'media'",
    "  para observaciones menores. Ante la duda, prefiere 'aprobado' o 'comentario'.",
    "",
    "Veredicto:",
    "- 'aprobado': los cambios corresponden a lo descrito (aunque incluyan soporte).",
    "- 'cambios_requeridos': hay invasión de alcance relevante o falta lo prometido.",
    "- 'comentario': solo observaciones menores que no justifican bloquear.",
    "No inventes cambios que no estén en el diff.",
    "",
    "Responde EXCLUSIVAMENTE en formato JSON con este esquema:",
    '{ "veredicto": "aprobado"|"cambios_requeridos"|"comentario", "alineado": boolean,',
    '  "confianza": number(0..1), "resumen": string(en español),',
    '  "hallazgos": [ { "tipo": string, "severidad": "baja"|"media"|"alta",',
    '                 "mensaje": string, "archivos": string[] } ] }',
  ].join("\n");

  const usuario = [
    `Repositorio: ${entrada.repositorio}`,
    `PR #${entrada.numeroPr}`,
    `Título: ${entrada.titulo}`,
    "",
    "DESCRIPCIÓN DEL PR:",
    entrada.descripcion || "(sin descripción)",
    "",
    `ARCHIVOS CAMBIADOS (${entrada.archivosCambiados.length}):`,
    entrada.archivosCambiados.join("\n") || "(ninguno)",
    "",
    `DIFF${truncado ? " (TRUNCADO)" : ""}:`,
    diff || "(vacío)",
  ].join("\n");

  const respuesta = await cliente.chat.completions.create({
    model: modelo,
    temperature: 0,
    response_format: { type: "json_object" },
    messages: [
      { role: "system", content: sistema },
      { role: "user", content: usuario },
    ],
  });

  const crudo = respuesta.choices?.[0]?.message?.content || "{}";
  return { motor: "ia", ...normalizarResultado(JSON.parse(crudo)) };
}

async function evaluar(entrada) {
  const claveApi = process.env.IA_CLAVE_API;
  const urlBase = process.env.IA_URL_BASE || "";
  const modelo = process.env.IA_MODELO || MODELO_POR_DEFECTO;

  if (!claveApi) return evaluarSimulado(entrada);

  try {
    return await evaluarConIA(entrada, { claveApi, urlBase, modelo });
  } catch (error) {
    // No tumbamos el workflow: devolvemos un veredicto válido que
    // deja claro que la IA no pudo ejecutarse.
    return {
      motor: "error",
      veredicto: "comentario",
      alineado: false,
      confianza: null,
      resumen: `El agente de IA no pudo completar la revisión: ${error.message}`,
      hallazgos: [
        { tipo: "error_agente", severidad: "alta", mensaje: String(error.message), archivos: [] },
      ],
    };
  }
}

async function principal() {
  const entrada = recopilarEntrada();
  const resultado = await evaluar(entrada);
  const modelo = process.env.IA_MODELO || MODELO_POR_DEFECTO;

  const salida = {
    version_esquema: VERSION_ESQUEMA,
    veredicto: resultado.veredicto, // aprobado | cambios_requeridos | comentario
    alineado: resultado.alineado,
    confianza: resultado.confianza,
    resumen: resultado.resumen,
    hallazgos: resultado.hallazgos,
    metadatos: {
      repositorio: entrada.repositorio,
      numero_pr: entrada.numeroPr,
      archivos_cambiados: entrada.archivosCambiados.length,
      adiciones: entrada.adiciones,
      eliminaciones: entrada.eliminaciones,
      motor: resultado.motor, // ia | simulado | error
      modelo: resultado.motor === "ia" ? modelo : null,
      generado_en: new Date().toISOString(),
    },
  };

  process.stdout.write(JSON.stringify(salida, null, 2) + "\n");
}

principal();
