# Token bucket behavior

GateFlow uses a token bucket for request admission. Each tenant or client has a capacity and refill rate. Tokens are replenished over time instead of being replenished all at once.

The bucket is modeled as a bounded, thread-safe counter. When a request arrives, the system checks whether enough tokens are available. If the request is allowed, one token is consumed. If not, the request is rejected with HTTP 429 and a retry delay.

This approach allows brief bursts while enforcing a sustainable average rate. Clients must treat 429 as a signal to slow down and retry after the suggested delay.
