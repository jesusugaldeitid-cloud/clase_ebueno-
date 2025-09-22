import socket
print ("ola 🌊 mundo")

hostname = socket.gethostname()
print(f"hostname: {hostname}")

IPAddress = socket.gethostbyname(hostname)
print(f"IP address: {IPAddress}")

for i in range(10):
    print(f"count: {i}")


numero_a = input("Dame el primer numero: ")
numero_b = input("Dame el segundo numero: ")
print(f"la sumas de los dos numeros es: {numero_a + numero_b}")
