# ZRE Core 2.6.5 — Administración y biblioteca de KPIs

Base estable: 4bb89bd460949c88df26255a6ce8739d38a449bb.
Handoff revisado: 5b14e5fb05361717132bff378c417eb0a2ae6551.

## Cambios
- Constructor de pantallas existente conservado; biblioteca de 92 KPIs con IDs estables.
- Fuentes existentes de combustible, estrategia, Coach y sesión reutilizadas.
- Protecciones SPOTTER para controles, neumáticos y frenos conservadas.
- Correcciones Senior: óptima numérica del Coach, STALE al desconectar, participantes por coche, humedad en porcentaje, cero válido, sectores ante saltos y cierre diferido, borradores persistentes durante actualizaciones, KPIs en pantallas base y catálogo sin SDK.
- Actualizaciones de texto evitan mutaciones DOM innecesarias; sin nuevos sockets ni polling.
- Corregidos saltos de línea literales en HTML/CSS heredados de Administración.

## QA
- 222 pruebas Python: OK.
- Todas las regresiones frontend: OK.
- Fixture DOM funcional: crear/guardar, IDs persistidos, cero válido, pantalla personalizada/base, restaurar y restablecer: OK.
- Servidor real de demostración: assets, versión y WebSocket PILOTO/SPOTTER: OK.
- 92 KPIs: aproximadamente 45 KB JSON con items/byId; generación de payload demo medio 0,23 ms (100 iteraciones locales).

## Limitaciones verificables
- Chromium no disponible; descarga falló. No se afirma prueba en navegador real ni QA visual.
- iRacing/Windows y coche real no disponibles: TC2/ABS/mapa/temperaturas/SR y cruces de sectores requieren prueba en pista.
- Sectores usan límites oficiales y timestamps muestreados; su precisión depende de la frecuencia SDK. No se inventan divisiones.
- Valores desconocidos permanecen WAITING/NOT_APPLICABLE. No se inventa posición de rejoin.

## Distribución
Se amplía el workflow existente para release-2.6.5. Updater y datos locales protegidos conservados.
