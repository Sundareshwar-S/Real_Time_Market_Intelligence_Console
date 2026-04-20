import { io } from "socket.io-client";
import { socketEndpoint } from "./endpoints";

export function createSocket() {
  return io(socketEndpoint, {
    transports: ["websocket", "polling"],
    autoConnect: true,
    reconnection: true,
    reconnectionAttempts: Infinity,
    reconnectionDelay: 1000,
    reconnectionDelayMax: 5000,
    timeout: 8000,
    tryAllTransports: true,
  });
}
