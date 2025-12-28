"""
Proxy management for anti-ban scraping.

Supports:
- Rotating residential proxies (Bright Data, Oxylabs, SmartProxy)
- Datacenter proxy pools
- SOCKS5 proxies
- Automatic rotation on errors
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


@dataclass
class ProxyConfig:
    """Configuration for proxy rotation."""
    
    # Proxy service credentials
    provider: str = "brightdata"  # brightdata, oxylabs, smartproxy, custom
    
    # Authentication
    username: Optional[str] = None
    password: Optional[str] = None
    api_key: Optional[str] = None
    
    # Proxy endpoints
    proxy_host: Optional[str] = None
    proxy_port: int = 22225
    
    # Rotation settings
    rotate_on_request: bool = True  # Get new IP each request
    rotate_on_error: bool = True    # Get new IP on 403/429
    sticky_session_mins: int = 0    # 0 = rotate every request
    
    # Geo targeting
    country: Optional[str] = None   # e.g., "us", "gb", "de"
    city: Optional[str] = None
    
    # Proxy type
    proxy_type: str = "residential"  # residential, datacenter, mobile
    
    # Fallback
    fallback_proxies: List[str] = field(default_factory=list)
    
    @classmethod
    def from_env(cls) -> "ProxyConfig":
        """Load configuration from environment variables."""
        return cls(
            provider=os.getenv("PROXY_PROVIDER", "brightdata"),
            username=os.getenv("PROXY_USERNAME"),
            password=os.getenv("PROXY_PASSWORD"),
            api_key=os.getenv("PROXY_API_KEY"),
            proxy_host=os.getenv("PROXY_HOST"),
            proxy_port=int(os.getenv("PROXY_PORT", "22225")),
            country=os.getenv("PROXY_COUNTRY"),
            proxy_type=os.getenv("PROXY_TYPE", "residential"),
        )
    
    @classmethod
    def brightdata(
        cls,
        username: str,
        password: str,
        country: Optional[str] = None,
        proxy_type: str = "residential",
    ) -> "ProxyConfig":
        """Configure Bright Data (formerly Luminati) proxy."""
        zone = "residential" if proxy_type == "residential" else "dc"
        return cls(
            provider="brightdata",
            username=username,
            password=password,
            proxy_host="brd.superproxy.io",
            proxy_port=22225,
            country=country,
            proxy_type=proxy_type,
        )
    
    @classmethod
    def oxylabs(
        cls,
        username: str,
        password: str,
        country: Optional[str] = None,
    ) -> "ProxyConfig":
        """Configure Oxylabs proxy."""
        return cls(
            provider="oxylabs",
            username=username,
            password=password,
            proxy_host="pr.oxylabs.io",
            proxy_port=7777,
            country=country,
        )
    
    @classmethod
    def smartproxy(
        cls,
        username: str,
        password: str,
        country: Optional[str] = None,
    ) -> "ProxyConfig":
        """Configure SmartProxy."""
        return cls(
            provider="smartproxy",
            username=username,
            password=password,
            proxy_host="gate.smartproxy.com",
            proxy_port=7000,
            country=country,
        )


class ProxyRotator:
    """
    Manages proxy rotation for anti-ban scraping.
    
    Example:
        >>> rotator = ProxyRotator(ProxyConfig.brightdata(
        ...     username="user",
        ...     password="pass",
        ...     country="us",
        ... ))
        >>> 
        >>> # Get proxy URL for requests
        >>> proxy_url = rotator.get_proxy()
        >>> 
        >>> # Report error to trigger rotation
        >>> rotator.report_error(proxy_url, 403)
    """
    
    def __init__(self, config: ProxyConfig):
        self.config = config
        self._session_id: Optional[str] = None
        self._session_start: float = 0
        self._error_count: Dict[str, int] = {}
        self._banned_ips: set = set()
        
    def get_proxy(self, target_url: Optional[str] = None) -> str:
        """
        Get a proxy URL for the request.
        
        Args:
            target_url: The URL being requested (for geo-targeting)
            
        Returns:
            Proxy URL in format http://user:pass@host:port
        """
        # Check if we need a new session
        if self._should_rotate_session():
            self._new_session()
        
        return self._build_proxy_url()
    
    def _should_rotate_session(self) -> bool:
        """Check if we should get a new session/IP."""
        if self.config.sticky_session_mins == 0:
            return True  # Rotate every request
            
        if self._session_id is None:
            return True
            
        elapsed = time.time() - self._session_start
        return elapsed > (self.config.sticky_session_mins * 60)
    
    def _new_session(self) -> None:
        """Generate a new session ID for sticky sessions."""
        self._session_id = f"session_{random.randint(100000, 999999)}"
        self._session_start = time.time()
        logger.debug(f"New proxy session: {self._session_id}")
    
    def _build_proxy_url(self) -> str:
        """Build the proxy URL with authentication and options."""
        config = self.config
        
        if config.provider == "brightdata":
            return self._build_brightdata_url()
        elif config.provider == "oxylabs":
            return self._build_oxylabs_url()
        elif config.provider == "smartproxy":
            return self._build_smartproxy_url()
        elif config.fallback_proxies:
            return random.choice(config.fallback_proxies)
        else:
            return self._build_generic_url()
    
    def _build_brightdata_url(self) -> str:
        """Build Bright Data proxy URL with session rotation."""
        config = self.config
        
        # Build username with options
        username_parts = [config.username]
        
        if config.country:
            username_parts.append(f"country-{config.country}")
        
        if self._session_id and config.sticky_session_mins > 0:
            username_parts.append(f"session-{self._session_id}")
        
        username = "-".join(username_parts)
        
        return f"http://{username}:{config.password}@{config.proxy_host}:{config.proxy_port}"
    
    def _build_oxylabs_url(self) -> str:
        """Build Oxylabs proxy URL."""
        config = self.config
        
        username = config.username
        if config.country:
            username = f"customer-{config.username}-cc-{config.country}"
        
        if self._session_id and config.sticky_session_mins > 0:
            username = f"{username}-sessid-{self._session_id}"
        
        return f"http://{username}:{config.password}@{config.proxy_host}:{config.proxy_port}"
    
    def _build_smartproxy_url(self) -> str:
        """Build SmartProxy URL."""
        config = self.config
        
        username = config.username
        if config.country:
            username = f"{username}-country-{config.country}"
        
        if self._session_id and config.sticky_session_mins > 0:
            username = f"{username}-session-{self._session_id}"
        
        return f"http://{username}:{config.password}@{config.proxy_host}:{config.proxy_port}"
    
    def _build_generic_url(self) -> str:
        """Build generic proxy URL."""
        config = self.config
        
        if config.username and config.password:
            return f"http://{config.username}:{config.password}@{config.proxy_host}:{config.proxy_port}"
        else:
            return f"http://{config.proxy_host}:{config.proxy_port}"
    
    def report_error(self, proxy_url: str, status_code: int) -> None:
        """
        Report an error for a proxy to trigger rotation.
        
        Args:
            proxy_url: The proxy that failed
            status_code: HTTP status code (403, 429, etc.)
        """
        self._error_count[proxy_url] = self._error_count.get(proxy_url, 0) + 1
        
        if status_code in (403, 429, 503):
            logger.warning(f"Proxy blocked (status {status_code}), rotating...")
            if self.config.rotate_on_error:
                self._new_session()
    
    def report_success(self, proxy_url: str) -> None:
        """Report successful request."""
        if proxy_url in self._error_count:
            del self._error_count[proxy_url]


class ProxyPool:
    """
    Pool of proxies for round-robin or weighted selection.
    
    Useful for custom proxy lists or multiple proxy providers.
    """
    
    def __init__(self, proxies: List[str], weights: Optional[List[float]] = None):
        """
        Initialize proxy pool.
        
        Args:
            proxies: List of proxy URLs
            weights: Optional weights for weighted selection
        """
        self.proxies = proxies
        self.weights = weights
        self._index = 0
        self._failures: Dict[str, int] = {}
        self._max_failures = 5
    
    def get_proxy(self) -> str:
        """Get next proxy from pool."""
        if self.weights:
            return random.choices(self.proxies, weights=self.weights, k=1)[0]
        
        # Round-robin
        proxy = self.proxies[self._index % len(self.proxies)]
        self._index += 1
        return proxy
    
    def report_failure(self, proxy: str) -> None:
        """Report a proxy failure."""
        self._failures[proxy] = self._failures.get(proxy, 0) + 1
        
        if self._failures[proxy] >= self._max_failures:
            logger.warning(f"Removing failed proxy: {proxy}")
            self.proxies = [p for p in self.proxies if p != proxy]
            if proxy in self._failures:
                del self._failures[proxy]
    
    def report_success(self, proxy: str) -> None:
        """Report successful request."""
        if proxy in self._failures:
            self._failures[proxy] = max(0, self._failures[proxy] - 1)


def get_rotating_user_agents() -> List[str]:
    """Get list of user agents for rotation."""
    return [
        # Chrome on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36",
        # Chrome on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        # Firefox on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        # Safari on Mac
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
        # Edge on Windows
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    ]


def random_user_agent() -> str:
    """Get a random user agent."""
    return random.choice(get_rotating_user_agents())

