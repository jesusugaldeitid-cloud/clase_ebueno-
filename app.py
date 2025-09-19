import socket
print ("ola 🌊 mundo")

hostname = socket.gethostname()
print(f"hostname: {hostname}")

IPAddress = socket.gethostbyname(hostname)
print(f"IP address: {IPAddress}")

for i in range(10):
    print(i