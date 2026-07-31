# Código de ejemplo. Sirve para tener "algo real" que modificar
# en las ramas feature y así generar un diff en los Pull Requests.


def saludar(nombre="equipo"):
    return f"Hey, {nombre}!"


# Ejecutable directo: `python3 src/saludar.py`
if __name__ == "__main__":
    print(saludar())
