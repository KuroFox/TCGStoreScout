# TCG Store Scout — MVP TCGplayer

MVP móvil para valorar cartas usando **TCGplayer como única fuente de mercado**.

## Arquitectura

El navegador no consulta TCGCSV ni TCGplayer directamente.

1. GitHub Actions descarga el snapshot diario de TCGplayer expuesto por TCGCSV.
2. El workflow genera un índice estático compacto.
3. GitHub Pages sirve la aplicación y sus datos por HTTPS.
4. Android busca localmente en esos archivos estáticos.

Esto evita los errores CORS / `file://` que aparecieron en los prototipos locales.

## Datos de mercado

Se muestran, cuando TCGplayer los publica para la impresión:

- Market Price
- Low Price
- Mid Price
- High Price
- Direct Low
- variante/printing (Normal, Holofoil, Reverse Holofoil, etc.)

Los ajustes por condición y las ofertas de compra son **estimaciones de la tienda**, no precios TCGplayer por condición.

## Juegos configurados

- Magic: The Gathering (1)
- Yu-Gi-Oh! (2)
- Pokémon (3)
- Digimon Card Game (63)
- One Piece Card Game (68)
- Disney Lorcana (71)

Si TCGCSV/TCGplayer devuelve cero productos para un juego, la interfaz lo marca como no disponible en el snapshot actual.

## Actualización

El workflow corre:
- al hacer push a `main`;
- manualmente con `workflow_dispatch`;
- cada día a las 21:35 UTC.

TCGCSV indica que su snapshot se actualiza una vez al día alrededor de las 20:00 UTC.

## Publicación

GitHub Pages debe estar configurado una sola vez con **Source: GitHub Actions**.

Después, el workflow `Build TCGplayer data and deploy` construye y publica automáticamente.
