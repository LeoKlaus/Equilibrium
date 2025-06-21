import logging
import socket

from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf
from zeroconf import IPVersion

class ZeroconfManager:

    info: AsyncServiceInfo|None = None
    zeroconf: AsyncZeroconf|None = None


    def register_service(self, name: str, description=None):
        if description is None:
            description = {}

        fqdn = socket.gethostname()
        ip_addr = socket.gethostbyname(fqdn)
        hostname = fqdn.split('.')[0]

        self.info = AsyncServiceInfo(
            "_equilibrium._tcp.local.",
            name + "._equilibrium._tcp.local.",
            addresses=[socket.inet_aton(ip_addr)],
            port=8000,
            properties=description,
            server=hostname,
        )

        self.zeroconf = AsyncZeroconf(ip_version=IPVersion.All)

    async def unregister_service(self):
        await self.zeroconf.async_unregister_service(self.info)
        await self.zeroconf.async_close()