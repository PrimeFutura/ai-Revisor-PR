# Guía de migración a GitHub Enterprise (Copilot / GitHub Models)

Este laboratorio usa hoy **OpenAI** con una API key personal. En tu organización
(**GitHub Enterprise**, donde solo se permite **Copilot**) la IA oficial se
consume a través de **GitHub Models**, que expone una **API compatible con OpenAI**.

> **La idea central:** el agente (`agente/revisor.py`) fue escrito para ser
> *agnóstico de proveedor* y **sin dependencias** (solo librería estándar). Por
> eso migrar **NO requiere reescribir código**: en la mayoría de los casos es
> solo **cambiar configuración** (3 variables de entorno + un permiso).

---

## 1. Confirmaciones con tu administrador de GitHub (hazlo primero)

Antes de tocar nada, verifica con quien administra la organización Enterprise:

- [ ] **¿Está habilitado *GitHub Models*** para la organización? (Ajustes de la
      organización → *Models* / *Copilot*). Si no lo está, pide que lo habiliten
      o usa la alternativa de **Azure OpenAI** (ver sección 6).
- [ ] **¿Qué modelos están disponibles y con qué nombre exacto?** En GitHub Models
      el nombre lleva prefijo de editor, p. ej. `openai/gpt-4o-mini`.
- [ ] **¿Se permiten las *actions* que usamos?** Solo usamos **actions oficiales de
      GitHub** (`actions/checkout`, `actions/setup-python`); no hay actions de
      terceros. Confirma que están en la lista permitida.
- [ ] **Permisos de los workflows:** que *Settings → Actions → General → Workflow
      permissions* esté en **"Read and write"**, para que el bot pueda **comentar**
      en el PR (`pull-requests: write`).

---

## 2. Cambios en el workflow (`.github/workflows/revision-pr.yml`)

Son **tres** ajustes puntuales.

### 2.1 Añadir el permiso `models: read`

```yaml
permissions:
  contents: read
  pull-requests: write
  models: read          # <-- AÑADIR: necesario para invocar GitHub Models
```

### 2.2 Cambiar las variables del paso "Ejecutar agente de IA"

**Antes (hoy, con OpenAI):**
```yaml
        env:
          IA_CLAVE_API: ${{ secrets.IA_CLAVE_API }}
          IA_MODELO: gpt-4o-mini
          # IA_URL_BASE vacío = OpenAI
```

**Después (en tu empresa, con GitHub Models):**
```yaml
        env:
          IA_CLAVE_API: ${{ github.token }}                     # el token del workflow ES la credencial
          IA_URL_BASE:  https://models.github.ai/inference      # endpoint de GitHub Models
          IA_MODELO:    openai/gpt-4o-mini                      # nombre con prefijo de editor
```

> El código ya envía la cabecera `Authorization: Bearer <IA_CLAVE_API>`, que es
> justo lo que GitHub Models espera. Por eso **no hay que tocar `revisor.py`**.

---

## 3. El *secret* `IA_CLAVE_API`

- Con **GitHub Models** la credencial es `${{ github.token }}`, así que **ya no
  necesitas** el secret `IA_CLAVE_API`. **Puedes eliminarlo** de
  *Settings → Secrets and variables → Actions*.
- (Solo si terminas usando **Azure OpenAI** en vez de GitHub Models, mantendrías
  un secret con la clave de Azure — ver sección 6.)

---

## 4. Protección de rama (aquí SÍ bloquea de verdad)

En el lab (repo privado en cuenta Free) las *rulesets* **no se aplicaban**. En
**Enterprise sí se aplican en repos privados**, así que el bloqueo del merge será
efectivo:

1. *Settings → Branches* (o *Rules → Rulesets*) → nueva regla para `main`.
2. **Require status checks to pass before merging** → selecciona el check
   **`Revisar PR`** (el nombre del job; aparece tras la primera ejecución).
3. (Opcional, más estricto) *Require a pull request before merging* y
   *Do not allow bypassing*.

---

## 5. Tabla resumen (hoy vs. empresa)

| Variable | Hoy (OpenAI) | En tu empresa (GitHub Models) |
|---|---|---|
| `IA_CLAVE_API` | `${{ secrets.IA_CLAVE_API }}` | `${{ github.token }}` |
| `IA_URL_BASE` | *(vacío = OpenAI)* | `https://models.github.ai/inference` |
| `IA_MODELO` | `gpt-4o-mini` | `openai/gpt-4o-mini` |
| Permiso extra | — | `models: read` |
| Secret | necesario | se puede eliminar |

---

## 6. Alternativa: Azure OpenAI (si NO hay GitHub Models)

Algunas organizaciones con Copilot usan **Azure OpenAI**. También es compatible
con OpenAI, pero cambia **la autenticación** (usa la cabecera `api-key` en lugar
de `Authorization: Bearer`) y la **URL** (incluye el *deployment* y `api-version`).

En ese caso:

- **Configuración:**
  - `IA_URL_BASE`: `https://<tu-recurso>.openai.azure.com/openai/deployments/<deployment>`
  - `IA_MODELO`: el nombre del *deployment*.
  - `IA_CLAVE_API`: guarda la clave de Azure como secret.
- **Pequeño cambio de código** en `agente/revisor.py`, función `evaluar_con_ia`:
  - Cambiar la cabecera de autenticación:
    ```python
    headers={
        "api-key": clave_api,          # Azure usa 'api-key' (no 'Authorization: Bearer')
        "Content-Type": "application/json",
    },
    ```
  - Añadir el parámetro `api-version` a la URL:
    ```python
    url = url_base.rstrip("/") + "/chat/completions?api-version=2024-08-01-preview"
    ```

> Si vas por GitHub Models (sección 2), **no** necesitas nada de esta sección 6.

---

## 7. Checklist rápido de migración

- [ ] Confirmar con el admin que **GitHub Models** está habilitado.
- [ ] Averiguar el **nombre exacto del modelo** disponible (`publisher/modelo`).
- [ ] Añadir `models: read` a `permissions`.
- [ ] Cambiar `IA_CLAVE_API` → `${{ github.token }}`, fijar `IA_URL_BASE` y `IA_MODELO`.
- [ ] Eliminar el secret `IA_CLAVE_API` (si usas GitHub Models).
- [ ] Verificar *Workflow permissions* = **Read and write** (para comentar).
- [ ] Configurar la **branch protection** en `main` con el check `Revisar PR`.
- [ ] Abrir un PR de prueba y validar: comentario del bot + veredicto + bloqueo.

---

## 8. Qué NO cambia

- **El código del agente** (`agente/revisor.py`): contrato JSON, lógica de
  coherencia por campo (título/descripción), motor simulado de respaldo, etc.
- **Los nombres** de variables de entorno, archivos y del check.
- **El flujo** del workflow (checkout → Python → diff → agente → comentario → gate).

Solo cambia la **configuración de la IA** (y, únicamente en el caso de Azure, una
cabecera y la URL).
