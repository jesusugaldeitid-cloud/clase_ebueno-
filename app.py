import socket
print ("ola 🌊 mundo")

hostname = socket.gethostname()
print(f"hostname: {hostname}")

IPAddress = socket.gethostbyname(hostname)
print(f"IP address: {IPAddress}")

for i in range(10):
    print(f"count: {i}")


numero_a = int(input("Dame el primer número: "))
numero_b = int(input("Dame el segundo número: "))
print(f"La suma de los dos números es: {numero_a + numero_b}")
print(f"La resta de los dos números es: {numero_a - numero_b}")

