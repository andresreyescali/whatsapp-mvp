# ===== Exercise 1 =========
def numeros(n):
    for i in range(1,n+1):
        yield i

z=list(numeros(10))
print(z)

# ======= Exercise 2 =========
lista=(i * i for i in range(10))
print(list(lista))

lista=(i * i for i in range(10))
for i in lista:
    print(i)

lista=(i * i for i in range(5))
print(next(lista))
print(next(lista))
print(next(lista))
print(next(lista))
print(next(lista))

# ====== Ejercicio 3 =======

def leer_archivo(ruta):
    with open(ruta) as f:
        for linea in f:
            yield linea.strip()

myPath="C:\AvarsSoftwareRepository\whatsapp-mvp\requirements.txt"

for i in leer_archivo(myPath):
    print(i)

