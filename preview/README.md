# ZRE VISUAL LAB — Frontend real y datos ficticios

**Repositorio:** zatzuro/ZRE-core. **Rama del código:** develop/visual-lab-web.

Visual Lab NO instala ZRE, no arranca iRacing y no se comunica con WebSocket ni APIs productivas.

## Publicación inicial (acción del propietario)

El repositorio es público, pero GitHub Pages debe habilitarse manualmente. En el repositorio abre:

1. **Settings → Pages**.
2. En **Build and deployment → Source**, selecciona **GitHub Actions**.
3. Conserva la configuración gratuita; no actives servicios de pago.
4. Abre **Actions → ZRE Visual Lab · QA and static-only publish**, busca la última ejecución de la rama **develop/visual-lab-web** y pulsa **Re-run all jobs**. El paso de publicación nativa se ejecutará si detecta GitHub Pages habilitado.
5. Abre **https://zatzuro.github.io/ZRE-core/**. Solo considera el despliegue terminado cuando Actions y la apertura desde navegador lo confirmen.

Si solo se necesita comprobar el artefacto previo a la activación, el workflow también deja una copia estática en la rama **gh-pages**. Esta rama **no equivale a una URL publicada** y sus pushes con GITHUB_TOKEN no sustituyen el despliegue nativo de Pages.

## Cómo funciona

- \`tools/build_visual_lab.py\` copia CSS y JS desde \`web/\` sin duplicarlos manualmente. El HTML original \`web/index.html\` se adapta para que use rutas relativas a \`/ZRE-core/\`.
- Solo dentro de \`dist/visual-lab/static/app.js\` se sustituye el transporte de \`/ws\` por una fuente de snapshots en memoria. **No se modifica \`web/app.js\` ni su WebSocket local**.
- \`preview/visual_lab.js\` produce fixtures deterministas: 44 escenarios de práctica, Quali, carrera, Spotter y estados extremos.
- \`preview/shell.html\` aporta controles de pantalla, escenario, escala, tamaño de letra, pausa y diagnóstico; el contenido visual es el auténtico dashboard embebido.
- El manifiesto de publicación muestra rama, versión y SHA del frontend probado.
- Todas las acciones que requieren ZRE real informan su limitación; no se escriben datos, no se importan setups ni se exportan reportes reales.

## Flujo de futuras correcciones de diseño

Desarrollo cambia \`web/\` en la rama de preview autorizada; el workflow ejecuta QA sintético y pruebas de navegador, compila de nuevo desde el frontend real y, cuando GitHub Pages esté habilitado con **Source → GitHub Actions**, publica el resultado. No hace merge a \`main\` ni publica un Windows release. Si se desea incluir correcciones de nuevos PR, integrar primero únicamente los cambios aprobados en la rama de preview, resolver conflictos y validar su QA.

## Validación

- \`python -m unittest discover -s tests -p test_visual_lab_build.py -v\`
- \`python tools/build_visual_lab.py --out dist/visual-lab\`
- \`python diagnostics/visual_lab_browser.py\` (requiere playwright y Chromium solo en CI).
- Los screenshots del workflow se conservan como artifact de siete días.

La política de costo adicional cero se satisface con repositorio público, Pages y runners estándar gratuitos, sin servicios externos de pago. No significa que se haya consultado la factura de la cuenta.
