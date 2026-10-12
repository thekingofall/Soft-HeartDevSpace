// Integration fixture: loopback readiness only; creates no real tunnel or DNS record.
using System;
using System.Net;
using System.Net.Sockets;
using System.Text;
class FakeCloudflared {
    static void Main(string[] args) {
        int index = Array.IndexOf(args, "--metrics");
        int port = int.Parse(args[index + 1].Split(':')[1]);
        var listener = new TcpListener(IPAddress.Loopback, port);
        listener.Start();
        while (true) {
            using (var client = listener.AcceptTcpClient()) {
                client.ReceiveTimeout = 3000;
                using (var stream = client.GetStream()) {
                    var buffer = new byte[4096];
                    stream.Read(buffer, 0, buffer.Length);
                    string body = "{\"readyConnections\":1}";
                    byte[] response = Encoding.ASCII.GetBytes("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: " + body.Length + "\r\nConnection: close\r\n\r\n" + body);
                    stream.Write(response, 0, response.Length);
                }
            }
        }
    }
}
