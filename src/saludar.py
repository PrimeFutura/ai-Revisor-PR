// Código de ejemplo. Sirve para tener "algo real" que modificar
// en las ramas feature y así generar un diff en los Pull Requests.

export function saludar(nombre = "equipo") {
  return `Hey, ${nombre}!`;
}

// Ejecutable directo: `npm run iniciar`
console.log(saludar());
