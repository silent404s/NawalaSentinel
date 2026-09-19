import asyncio
import time
import logging
import dns.asyncresolver
import dns.exception
import httpx
from typing import Dict, List, Tuple, Any

from app.config import settings

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("nawala_checker")

class OperatorBlockChecker:
    """
    Engine Asinkron Pemantau Pemblokiran Domain Nawala & Internet Positif
    untuk Operator Seluler Indonesia (Telkomsel, XL, Tri, IM3).
    """

    def __init__(self, concurrency_limit: int = 30):
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    async def check_dns_operator(self, domain: str, operator_name: str, dns_servers: List[str]) -> Tuple[bool, List[str], str]:
        """
        Kueri DNS secara langsung ke Server DNS operator seluler.
        Return: (is_blocked: bool, resolved_ips: List[str], reason: str)
        """
        if not dns_servers:
            return False, [], "No DNS server defined"

        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = dns_servers
        resolver.timeout = 3.0
        resolver.lifetime = 4.0

        try:
            # Kueri DNS A Record
            answers = await resolver.resolve(domain, 'A')
            resolved_ips = [rdata.address for rdata in answers]

            # Cek apakah IP yang didapat merupakan IP Sinkhole Pemblokiran
            for ip in resolved_ips:
                for sinkhole in settings.KNOWN_SINKHOLE_IPS:
                    if ip.startswith(sinkhole) or ip == sinkhole:
                        return True, resolved_ips, f"DNS Sinkhole IP terdeteksi ({ip}) via {operator_name} DNS"

            return False, resolved_ips, "DNS Clean"

        except dns.resolver.NXDOMAIN:
            # Bebas atau NXDOMAIN asli. Bandingkan dengan DNS Publik jika perlu
            return False, [], "NXDOMAIN (Domain tidak ditemukan)"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False, [], "No Answer from DNS Server"
        except dns.exception.Timeout:
            return False, [], "DNS Query Timeout"
        except Exception as e:
            return False, [], f"DNS Error: {str(e)}"

    async def check_http_operator(self, domain: str, operator_name: str, proxy_url: str = "") -> Tuple[bool, str]:
        """
        Pengecekan HTTP/HTTPS untuk mendeteksi redirection ke Blockpage (Internet Positif / Nawala)
        atau kecocokan kata kunci (signature) halaman blokir ISP.
        Return: (is_blocked: bool, reason: str)
        """
        target_urls = [f"http://{domain}", f"https://{domain}"]
        
        # Opsi HTTP client dengan Proxy jika dikonfigurasi per operator
        client_kwargs = {
            "headers": self.headers,
            "timeout": httpx.Timeout(6.0, connect=4.0),
            "follow_redirects": True,
            "verify": False  # Mengabaikan SSL error saat inspeksi blokir
        }

        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            for url in target_urls:
                try:
                    response = await client.get(url)
                    final_url = str(response.url).lower()

                    # 1. Inspeksi URL Redirect (contoh: internetpositif.id, siteblocked, pos-blokir)
                    for signature in settings.BLOCKPAGE_SIGNATURES:
                        if signature in final_url:
                            return True, f"HTTP Redirect ke Halaman Blokir: {final_url}"

                    # 2. Inspeksi Body HTML (Content matching)
                    body_text = response.text.lower()
                    for signature in settings.BLOCKPAGE_SIGNATURES:
                        if signature in body_text and len(body_text) < 50000: # hanya periksa halaman ringan/blokir
                            return True, f"Halaman Blokir Terdeteksi Signature '{signature}' pada body HTML"

                except (httpx.ConnectTimeout, httpx.ReadTimeout):
                    continue
                except httpx.HTTPError:
                    continue
                except Exception:
                    continue

        return False, "HTTP Clean / No Block Signature"

    async def check_domain_for_operator(self, domain: str, operator_name: str) -> Dict[str, Any]:
        """
        Memeriksa 1 domain spesifik untuk 1 operator tertentu.
        """
        start_time = time.time()
        dns_servers = settings.OPERATOR_DNS.get(operator_name, [])
        proxy_url = settings.OPERATOR_PROXIES.get(operator_name, "")

        # Step 1: Cek DNS Operator
        dns_blocked, resolved_ips, dns_reason = await self.check_dns_operator(domain, operator_name, dns_servers)
        
        if dns_blocked:
            latency = round((time.time() - start_time) * 1000, 2)
            return {
                "operator": operator_name,
                "status": "BLOCKED",
                "resolved_ips": ", ".join(resolved_ips),
                "block_reason": dns_reason,
                "latency_ms": latency
            }

        # Step 2: Cek HTTP / Proxy / Signature jika DNS tidak terindikasi sinkhole
        http_blocked, http_reason = await self.check_http_operator(domain, operator_name, proxy_url)
        
        latency = round((time.time() - start_time) * 1000, 2)

        if http_blocked:
            return {
                "operator": operator_name,
                "status": "BLOCKED",
                "resolved_ips": ", ".join(resolved_ips),
                "block_reason": http_reason,
                "latency_ms": latency
            }

        # Jika lolos kedua pengecekan
        return {
            "operator": operator_name,
            "status": "NORMAL",
            "resolved_ips": ", ".join(resolved_ips),
            "block_reason": "Domain Aktif & Normal",
            "latency_ms": latency
        }

    async def check_domain_all_operators(self, domain: str) -> Dict[str, Any]:
        """
        Memeriksa 1 domain secara paralel di 4 operator (Telkomsel, XL, IM3, Tri).
        """
        async with self.semaphore:
            logger.info(f"Mulai pengecekan domain: {domain}")
            operators = ["Telkomsel", "XL", "IM3", "Tri"]
            
            tasks = [self.check_domain_for_operator(domain, op) for op in operators]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            operator_results = {}
            blocked_count = 0
            normal_count = 0

            for res in results:
                if isinstance(res, Exception):
                    logger.error(f"Error checking domain {domain}: {res}")
                    continue
                
                op_name = res["operator"]
                operator_results[op_name] = res
                
                if res["status"] == "BLOCKED":
                    blocked_count += 1
                elif res["status"] == "NORMAL":
                    normal_count += 1

            # Hitung overall status domain
            if blocked_count == len(operators):
                overall_status = "BLOCKED" # Terblokir di semua operator
            elif blocked_count > 0:
                overall_status = "MIXED"   # Terblokir di sebagian operator
            else:
                overall_status = "NORMAL"  # Aktif di semua operator

            return {
                "domain": domain,
                "overall_status": overall_status,
                "operator_results": operator_results,
            }

    async def check_batch_domains(self, domain_list: List[str]) -> List[Dict[str, Any]]:
        """
        Memeriksa massal (ratusan domain sekaligus) secara paralel.
        """
        tasks = [self.check_domain_all_operators(domain) for domain in domain_list]
        return await asyncio.gather(*tasks)

# Global Instance
checker_engine = OperatorBlockChecker(concurrency_limit=settings.CONCURRENT_CHECKS)
