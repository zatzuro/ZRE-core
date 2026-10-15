# ZRE continuidad — release 2.6.7.1

Fecha: 2026-10-15. Senior autorizado a corregir e integrar/publicar.
Base estable: 878babe278ef8b4618b88ad500f40d0295ee16a6, v2.6.7.
PR #17 contiene íntegramente PR #16 (ambos partían de 98c8025); realizar una única integración y cerrar #16 como sustituido una vez comprobada.
Correcciones y matriz P1: diagnostics/QA-2.6.7.1.md. La política conservadora separa inspección observada de atribución física y comparación del mismo juego; no inventa desgaste cero.
Estado de publicación: pendiente de CI por SHA y job release-2671; consultar main, tag v2.6.7.1, Actions y release GitHub para el estado vivo. El SHA del candidato es el SHA de activación y tag: el job solo avanza main tras todos los checks.
Visual Lab: PR #18, rama develop/visual-lab-web, SHA observado 6bebfdd5d38ae1178135224fb378a0e58bd085bf; base funcional anterior 98c8025. Pendiente reconciliar dependencias antes de integrar. No se declara URL pública sin verificar.
Validación física de iRacing/PC del usuario pendiente, expresamente separada de CI Windows/demo. No es evidencia de causa histórica de stint.
