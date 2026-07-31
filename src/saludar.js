// Código de ejemplo. Sirve para tener "algo real" que modificar
// en las ramas feature y así generar un diff en los Pull Requests.

export function greet(name = "equipo") {
  return `Hey, ${name}!`;
}

// Ejecutable directo: `npm start`
console.log(greet());
