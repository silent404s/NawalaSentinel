import asyncio
import time
import logging
import re
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
    untuk Operator Seluler Indonesia (Telkomsel, XL, Tri, IM3) + Database Komdigi TrustPositif.
    """

    def __init__(self, concurrency_limit: int = 30):
        self.semaphore = asyncio.Semaphore(concurrency_limit)
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7",
        }
        self._tp_csrf = None
        self._tp_client = None
        self._tp_lock = asyncio.Lock()

    async def check_trustpositif(self, domain: str) -> bool:
        """
        Pengecekan ke Database Resmi TrustPositif Komdigi / Nawala.
        Return True jika domain terdaftar sebagai diblokir (Status: 'Ada').
        """
        host = domain.split("/")[0].strip().lower()
        async with self._tp_lock:
            if self._tp_client is None or self._tp_client.is_closed:
                self._tp_client = httpx.AsyncClient(verify=False, timeout=6.0)

            # Ambil CSRF token jika belum ada
            if not self._tp_csrf:
                try:
                    r = await self._tp_client.get('https://trustpositif.komdigi.go.id/', timeout=4.0)
                    m = re.search(r"['\"]csrf_token['\"]\s*:\s*['\"]([a-f0-9]+)['\"]", r.text)
                    if m:
                        self._tp_csrf = m.group(1)
                except Exception as e:
                    logger.warning(f"Gagal mengambil token TrustPositif: {e}")

        if self._tp_csrf:
            try:
                res = await self._tp_client.post(
                    'https://trustpositif.komdigi.go.id/Rest_server/getrecordsname_home',
                    data={'csrf_token': self._tp_csrf, 'name': host},
                    headers={
                        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Referer': 'https://trustpositif.komdigi.go.id/'
                    },
                    timeout=5.0
                )
                if res.status_code == 200:
                    data = res.json()
                    for item in data.get('values', []):
                        if item.get('Status', '').lower() == 'ada':
                            return True
                else:
                    # Reset CSRF jika status code bukan 200 (token invalid/expired)
                    self._tp_csrf = None
            except Exception as e:
                logger.warning(f"Error query TrustPositif untuk {domain}: {e}")
                self._tp_csrf = None
        return False

    async def check_public_dns(self, domain: str) -> Tuple[bool, List[str], str]:
        """
        Kueri DNS Publik (1.1.1.1, 8.8.8.8) untuk memvalidasi apakah domain benar-benar terdaftar dan aktif.
        """
        host = domain.split("/")[0].strip()
        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = settings.PUBLIC_DNS
        resolver.timeout = 2.5
        resolver.lifetime = 3.5

        try:
            answers = await resolver.resolve(host, 'A')
            ips = [rdata.address for rdata in answers]
            return True, ips, "DNS Resolved"
        except dns.resolver.NXDOMAIN:
            return False, [], "NXDOMAIN (Domain tidak terdaftar di DNS publik)"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False, [], "No Answer dari DNS Publik"
        except dns.exception.Timeout:
            return False, [], "DNS Query Timeout ke DNS Publik"
        except Exception as e:
            return True, [], f"Public DNS Notice: {str(e)}"

    async def check_dns_operator(self, domain: str, operator_name: str, dns_servers: List[str]) -> Tuple[bool, List[str], str]:
        """
        Kueri DNS secara langsung ke Server DNS operator seluler.
        Return: (is_blocked: bool, resolved_ips: List[str], reason: str)
        """
        if not dns_servers:
            return False, [], "No DNS server defined"

        host = domain.split("/")[0].strip()
        resolver = dns.asyncresolver.Resolver(configure=False)
        resolver.nameservers = dns_servers
        resolver.timeout = 3.0
        resolver.lifetime = 3.5

        try:
            # Kueri DNS A Record
            answers = await resolver.resolve(host, 'A')
            resolved_ips = [rdata.address for rdata in answers]

            # Cek apakah IP yang didapat merupakan IP Sinkhole Pemblokiran
            for ip in resolved_ips:
                for sinkhole in settings.KNOWN_SINKHOLE_IPS:
                    if ip.startswith(sinkhole) or ip == sinkhole:
                        return True, resolved_ips, f"DNS Sinkhole IP terdeteksi ({ip}) via {operator_name} DNS"

            return False, resolved_ips, "DNS Clean"

        except dns.resolver.NXDOMAIN:
            return False, [], "NXDOMAIN"
        except (dns.resolver.NoAnswer, dns.resolver.NoNameservers):
            return False, [], "No Answer"
        except dns.exception.Timeout:
            return False, [], "DNS Timeout"
        except Exception as e:
            return False, [], f"DNS Error: {str(e)}"

    async def check_cloudflare_status(self, domain: str) -> Tuple[str, str]:
        """
        Pengecekan independen khusus status Cloudflare (Suspected Phishing, Cloudflare Block).
        Mendukung URL dengan path spesifik (misal: vpngwnlog.com/login)
        maupun root domain (yang akan otomatis menguji /login juga).
        Return: (cf_status: 'PHISHING' | 'CLEAN', cf_reason: str)
        """

        if "/" in domain:
            target_urls = [
                f"https://{domain}",
                f"http://{domain}",
            ]
        else:
            target_urls = [
                f"https://{domain}",
                f"http://{domain}",
                f"https://{domain}/login",
            ]

        client_kwargs = {
            "headers": self.headers,
            "timeout": httpx.Timeout(6.0, connect=3.5),
            "follow_redirects": True,
            "verify": False
        }

        async with httpx.AsyncClient(**client_kwargs) as client:
            for url in target_urls:
                try:
                    response = await client.get(url)
                    final_url = str(response.url).lower()
                    body_text = response.text.lower()

                    # Deteksi Cloudflare / Anti-Phishing Warnings
                    for p_sig in settings.PHISHING_SIGNATURES:
                        if p_sig in body_text or p_sig in final_url:
                            return "PHISHING", f"Cloudflare Suspected Phishing Terdeteksi pada {url}"

                except (httpx.ConnectTimeout, httpx.ReadTimeout):
                    continue
                except httpx.HTTPError:
                    continue
                except Exception:
                    continue

        return "CLEAN", "Cloudflare Clean"

    async def check_http_operator(self, domain: str, operator_name: str, proxy_url: str = "") -> Tuple[str, str]:
        """
        Pengecekan HTTP/HTTPS untuk mendeteksi Blockpage Nawala / Internet Positif Redirection & Signatures.
        Return: (status: str, reason: str) -> status: 'BLOCKED' or 'NORMAL'
        """
        target_urls = [
            f"https://{domain}",
            f"http://{domain}",
        ]
        
        client_kwargs = {
            "headers": self.headers,
            "timeout": httpx.Timeout(6.0, connect=3.5),
            "follow_redirects": True,
            "verify": False
        }

        if proxy_url:
            client_kwargs["proxy"] = proxy_url

        async with httpx.AsyncClient(**client_kwargs) as client:
            for url in target_urls:
                try:
                    response = await client.get(url)
                    final_url = str(response.url).lower()
                    body_text = response.text.lower()

                    # 1. Inspeksi URL Redirect Nawala / Internet Positif
                    for signature in settings.BLOCKPAGE_SIGNATURES:
                        if signature in final_url:
                            return "BLOCKED", f"HTTP Redirect ke Halaman Blokir: {final_url}"

                    # 2. Inspeksi Body HTML Nawala
                    for signature in settings.BLOCKPAGE_SIGNATURES:
                        if signature in body_text and len(body_text) < 50000:
                            return "BLOCKED", f"Halaman Blokir Terdeteksi Signature '{signature}' pada body HTML"

                except (httpx.ConnectTimeout, httpx.ReadTimeout):
                    continue
                except httpx.HTTPError:
                    continue
                except Exception:
                    continue

        return "NORMAL", "HTTP Clean / No Block Signature"

    async def check_domain_for_operator(self, domain: str, operator_name: str, public_ips: List[str], tp_blocked: bool = False) -> Dict[str, Any]:
        """
        Memeriksa 1 domain spesifik untuk 1 operator tertentu.
        Memprioritaskan database resmi TrustPositif, kueri DNS operator, dan inspeksi HTTP/HTTPS.
        """
        start_time = time.time()
        dns_servers = settings.OPERATOR_DNS.get(operator_name, [])
        proxy_url = settings.OPERATOR_PROXIES.get(operator_name, "")

        # 1. Jika terdaftar di Database Resmi TrustPositif Komdigi / Nawala
        if tp_blocked:
            latency = round((time.time() - start_time) * 1000, 2)
            return {
                "operator": operator_name,
                "status": "BLOCKED",
                "resolved_ips": ", ".join(public_ips) if public_ips else "",
                "block_reason": "Terdaftar pada Database Pemblokiran TrustPositif Komdigi / Nawala",
                "latency_ms": latency or 30.0
            }

        # 2. Kueri DNS Operator (Cek IP Sinkhole)
        dns_blocked, resolved_ips, dns_reason = await self.check_dns_operator(domain, operator_name, dns_servers)
        latency = round((time.time() - start_time) * 1000, 2)

        if dns_blocked:
            return {
                "operator": operator_name,
                "status": "BLOCKED",
                "resolved_ips": ", ".join(resolved_ips),
                "block_reason": dns_reason,
                "latency_ms": latency
            }

        # 3. Inspeksi HTTP/HTTPS (Cek Halaman Blokir Nawala / Redirect)
        http_status, http_reason = await self.check_http_operator(domain, operator_name, proxy_url)
        latency = round((time.time() - start_time) * 1000, 2)

        if http_status == "BLOCKED":
            return {
                "operator": operator_name,
                "status": "BLOCKED",
                "resolved_ips": ", ".join(resolved_ips or public_ips),
                "block_reason": http_reason,
                "latency_ms": latency
            }

        # 4. Jika DNS operator timeout dan tidak ada proxy yang dikonfigurasi,
        # namun domain bebas dari TrustPositif dan HTTP bersih, maka status adalah NORMAL.
        if dns_reason == "DNS Timeout" and not proxy_url:
            return {
                "operator": operator_name,
                "status": "NORMAL",
                "resolved_ips": ", ".join(public_ips) if public_ips else "",
                "block_reason": f"Domain Aktif & Bebas Nawala (DNS {operator_name} Timeout)",
                "latency_ms": latency
            }

        # 5. Jika lolos seluruh lapisan pengecekan (Bebas Blokir)
        return {
            "operator": operator_name,
            "status": "NORMAL",
            "resolved_ips": ", ".join(resolved_ips or public_ips),
            "block_reason": "Domain Aktif & Bebas Nawala",
            "latency_ms": latency
        }

    async def check_domain_all_operators(self, domain: str) -> Dict[str, Any]:
        """
        Memeriksa 1 domain secara paralel di 4 operator (Telkomsel, XL, IM3, Tri).
        Memprioritaskan database TrustPositif Komdigi di awal, diikuti DNS operator & Cloudflare.
        """
        async with self.semaphore:
            logger.info(f"Mulai pengecekan domain: {domain}")
            operators = ["Telkomsel", "XL", "IM3", "Tri"]

            # 1. PRIORITAS UTAMA: Cek Database Resmi Komdigi TrustPositif & Cloudflare Status
            tp_task = self.check_trustpositif(domain)
            cf_task = self.check_cloudflare_status(domain)

            tp_res, cf_res = await asyncio.gather(tp_task, cf_task, return_exceptions=True)
            tp_blocked = bool(tp_res) if not isinstance(tp_res, Exception) else False

            if isinstance(cf_res, Exception):
                logger.error(f"Error checking cloudflare for {domain}: {cf_res}")
                cf_status, cf_reason = "CLEAN", f"Error: {cf_res}"
            else:
                cf_status, cf_reason = cf_res

            # Jika TrustPositif menyatakan "Ada" (BLOCKED), langsung vonis BLOCKED untuk seluruh operator!
            if tp_blocked:
                # Coba ambil public IPs jika ada untuk kelengkapan info
                public_ok, public_ips, _ = await self.check_public_dns(domain)
                ip_str = ", ".join(public_ips) if (public_ok and public_ips) else ""
                tp_results = {
                    op: {
                        "operator": op,
                        "status": "BLOCKED",
                        "resolved_ips": ip_str,
                        "block_reason": "Terdaftar pada Database Pemblokiran TrustPositif Komdigi / Nawala",
                        "latency_ms": 30.0
                    }
                    for op in operators
                }
                return {
                    "domain": domain,
                    "overall_status": "BLOCKED",
                    "cf_status": cf_status,
                    "cf_reason": cf_reason,
                    "operator_results": tp_results
                }

            # 2. Jika Tidak Ada di TrustPositif, validasi ke DNS Publik
            public_ok, public_ips, public_msg = await self.check_public_dns(domain)
            if not public_ok:
                # Bebas Nawala, namun domain tidak aktif/resolving di DNS publik
                nx_results = {
                    op: {
                        "operator": op,
                        "status": "NORMAL",
                        "resolved_ips": "",
                        "block_reason": f"Bebas Nawala ({public_msg})",
                        "latency_ms": 0.0
                    }
                    for op in operators
                }
                return {
                    "domain": domain,
                    "overall_status": "NORMAL",
                    "cf_status": cf_status,
                    "cf_reason": f"Bebas Nawala ({public_msg})",
                    "operator_results": nx_results
                }

            # 3. Pengecekan 4 Operator ISP (DNS Sinkhole & HTTP Inspection)
            op_tasks = [self.check_domain_for_operator(domain, op, public_ips, tp_blocked=False) for op in operators]
            op_results_list = await asyncio.gather(*op_tasks, return_exceptions=True)

            operator_results = {}
            blocked_count = 0
            normal_count = 0
            timeout_count = 0

            for res in op_results_list:
                if isinstance(res, Exception):
                    logger.error(f"Error checking operator for domain {domain}: {res}")
                    continue
                
                op_name = res["operator"]
                operator_results[op_name] = res
                
                if res["status"] == "BLOCKED":
                    blocked_count += 1
                elif res["status"] == "NORMAL":
                    normal_count += 1
                elif res["status"] == "TIMEOUT":
                    timeout_count += 1

            # Hitung overall status Nawala / ISP
            if blocked_count == len(operators):
                overall_status = "BLOCKED"
            elif blocked_count > 0:
                overall_status = "MIXED"
            elif normal_count > 0:
                overall_status = "NORMAL"
            elif timeout_count == len(operators):
                overall_status = "TIMEOUT"
            else:
                overall_status = "UNCHECKED"

            return {
                "domain": domain,
                "overall_status": overall_status,
                "cf_status": cf_status,
                "cf_reason": cf_reason,
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
