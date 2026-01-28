# Chess Mentor

Chess Mentor es una plataforma de entrenamiento de ajedrez, desarrollada con Django, utiliza Pico CSS para el estilo, buscando un diseño minimalista.
Utiliza AlpineJS como microframework javascript.
Para visualizar puzzles utiliza ChessJS y Chessboard Element JS, este ultimo es una variación de Chessboard.js pero utilizando una etiqueta html personalizada llamada "chess-board".

El objetivo es Chess Mentor es utilizar temas y asignarles puntuación Elo a cada una, de manera que se puede saber donde un jugador es mas fuerte o debil, que se puede interpretar como en que temas conoce mejor o peor el patrón para resolver. Cada semana se elige un set de temas que el usuario debe entrenar.

Los puzzles se eligen de una base de datos de puzzles de lichess.

# Estructura del proyecto

- "core/" es el núcleo del proyecto, donde se ubica settings.py, urls.py
- "chess/" es la app principal, donde se trabaja la logica de negocio.
- "lichess_db_puzzle.csv" es la base de datos original de puzzles de lichess.
- "lichess_puzzles.sqlite3" es la base de datos importada a sqlite y reducido su tamaño.
- ".env/" es el entorno virtual del proyecto.
- ".secret" es donde se ubica las variables de entorno.

# Instrucciones de pruebas (testing)

- No agregar tests.py, las pruebas debe realizarla el usuario que te de las instrucciones.
- No modifiques las migraciones ya generadas.

# Estilo de código y convenciones

- html, js y css siguiendo el estilo y convenciones de Prettier.
- En código python seguir las convenciones de PEP8.
- Agregar documentación y comentarios donde sea necesario.
- No escribir código complejo, siempre debe ser simple, sencillo, facil de leer y comprender.
