# ai-Revisor-PR

Laboratorio para aprender **GitHub Actions** de forma progresiva, con el objetivo
final de que al abrir un **Pull Request** se dispare un **agente de IA** que valide
si lo que el desarrollador describió en el PR coincide con el **diff** de código
(evitar que se "cuele" más de lo descrito). El agente devolverá un **veredicto en
formato JSON estándar**.

## Roadmap por fases

| Fase | Objetivo |
|------|----------|
| **0** | Flujo completo mínimo: repo → rama feature → PR → un workflow que deja **traza** de que se ejecutó. |
| **1** | Leer el **contexto** del PR (título, descripción, autor, rama). |
| **2** | Obtener el **diff** / archivos cambiados del PR. |
| **3** | Pasar los datos a un **script Node.js** que devuelve un **JSON estándar** (veredicto *mock*, aún sin IA). |
| **4** | Integrar el **agente de IA** real (proveedor a definir) con el prompt de validación descripción ↔ diff. |
| **5** | Endurecer: convertir el veredicto en **status check** que pueda bloquear el merge. |

## Estado actual

- ✅ **Fase 0** en curso.

## Estructura

```
.
├── .github/
│   └── workflows/
│       └── pr-check.yml     # Workflow que se dispara en cada Pull Request
├── src/
│   └── greet.js             # Código de ejemplo para modificar en las ramas feature
├── package.json
└── README.md
```
