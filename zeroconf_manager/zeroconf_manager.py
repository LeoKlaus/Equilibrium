import socket

from zeroconf import IPVersion
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf


def get_lan_ip() -> str:
    """The machine's actual outbound LAN address, independent of
    hostname/DNS/hosts-file resolution entirely. Also used by
    api.lifespan for the "Hub is ready" startup message, alongside
    this module's own use of it when building the mDNS record."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp_socket:
        udp_socket.connect(("8.8.8.8", 80))
        return udp_socket.getsockname()[0]


class ZeroconfManager:

    info: AsyncServiceInfo|None = None
    zeroconf: AsyncZeroconf|None = None

    advertised_name: str | None = None
    advertised_ip: str | None = None
    advertised_port: int | None = None

    async def register_service(self, name: str, description=None, port: int = 8000):
        if description is None:
            description = {}

        fqdn = socket.gethostname()
        ip_addr = get_lan_ip()
        hostname = fqdn.split('.')[0]

        self.info = AsyncServiceInfo(
            "_equilibrium._tcp.local.",
            name + "._equilibrium._tcp.local.",
            addresses=[socket.inet_aton(ip_addr)],
            port=port,
            properties=description,
            server=hostname,
        )

        self.zeroconf = AsyncZeroconf(ip_version=IPVersion.V4Only)
        await self.zeroconf.async_register_service(info=self.info)

        self.advertised_name = name
        self.advertised_ip = ip_addr
        self.advertised_port = port

    async def unregister_service(self):
        goodbye = await self.zeroconf.async_unregister_service(self.info)
        await goodbye
        await self.zeroconf.async_close()
