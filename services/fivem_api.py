import aiohttp
import asyncio
import logging
import json
import re
from typing import Optional, Dict, List, Any
from datetime import datetime

logger = logging.getLogger(__name__)

class FiveMAPI:
    """Robust FiveM Server API Client - Handles all response types"""
    
    def __init__(self, base_url: str, timeout: int = 15):
        # Clean and validate base URL
        self.base_url = base_url.rstrip('/')
        self.timeout = aiohttp.ClientTimeout(total=timeout)
        self.session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create HTTP session with proper headers"""
        if self.session is None or self.session.closed:
            headers = {
                'User-Agent': 'MotionlifeBot/1.0 (FiveM Server Monitor)',
                'Accept': 'application/json, text/plain, text/html, */*',
                'Accept-Encoding': 'gzip, deflate',
                'Connection': 'keep-alive'
            }
            self.session = aiohttp.ClientSession(
                timeout=self.timeout,
                headers=headers
            )
        return self.session
    
    async def _make_request(self, endpoint: str) -> Optional[Dict[str, Any]]:
        """Make HTTP request to FiveM API with robust parsing"""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            session = await self._get_session()
            
            async with session.get(url) as response:
                logger.debug(f"Request to {url} - Status: {response.status}, Content-Type: {response.content_type}")
                
                if response.status == 200:
                    # Get raw response
                    try:
                        raw_text = await response.text(encoding='utf-8')
                    except UnicodeDecodeError:
                        # Try with different encoding
                        try:
                            raw_bytes = await response.read()
                            raw_text = raw_bytes.decode('utf-8', errors='ignore')
                        except:
                            raw_text = str(await response.read())
                    
                    # Clean and validate response
                    if not raw_text or not raw_text.strip():
                        logger.warning(f"Empty response from {url}")
                        return None
                    
                    cleaned_text = raw_text.strip()
                    
                    # Try to parse as JSON
                    return self._parse_json_response(cleaned_text, url)
                    
                elif response.status == 404:
                    logger.warning(f"Endpoint not found: {url}")
                    return None
                elif response.status == 503:
                    logger.warning(f"Server unavailable: {url}")
                    return None
                else:
                    logger.warning(f"HTTP {response.status} from {url}")
                    return None
                    
        except asyncio.TimeoutError:
            logger.error(f"Timeout requesting {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Client error requesting {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error requesting {url}: {e}")
            return None
    
    def _parse_json_response(self, text: str, url: str) -> Optional[Dict[str, Any]]:
        """Parse JSON response with multiple fallback methods"""
        
        # Method 1: Direct JSON parsing
        try:
            data = json.loads(text)
            logger.debug(f"Successfully parsed JSON from {url}")
            return data
        except json.JSONDecodeError:
            pass
        
        # Method 2: Check if it looks like JSON and clean it
        if (text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']')):
            try:
                # Remove any non-JSON content before/after
                # Find first { or [
                start_idx = min(text.find('{'), text.find('['))
                if start_idx == -1:
                    start_idx = max(text.find('{'), text.find('['))
                
                # Find last } or ]
                end_idx = max(text.rfind('}'), text.rfind(']'))
                
                if start_idx >= 0 and end_idx > start_idx:
                    clean_json = text[start_idx:end_idx+1]
                    data = json.loads(clean_json)
                    logger.debug(f"Successfully parsed cleaned JSON from {url}")
                    return data
            except (json.JSONDecodeError, ValueError):
                pass
        
        # Method 3: Try to extract JSON from HTML response
        if '<html' in text.lower() or '<!doctype' in text.lower():
            # Sometimes FiveM servers wrap JSON in HTML
            json_match = re.search(r'(\{.*\}|\[.*\])', text, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    logger.debug(f"Extracted JSON from HTML response from {url}")
                    return data
                except json.JSONDecodeError:
                    pass
        
        # Method 4: Check for JSONP or JavaScript wrapping
        jsonp_match = re.search(r'[\w\.]+\s*\(\s*(\{.*\}|\[.*\])\s*\)', text, re.DOTALL)
        if jsonp_match:
            try:
                data = json.loads(jsonp_match.group(1))
                logger.debug(f"Extracted JSON from JSONP response from {url}")
                return data
            except json.JSONDecodeError:
                pass
        
        # Log the failure with sample of response
        logger.error(f"Failed to parse JSON from {url}")
        logger.debug(f"Response sample (first 200 chars): {text[:200]}")
        logger.debug(f"Response sample (last 200 chars): {text[-200:]}")
        return None
    
    async def get_server_info(self) -> Optional[Dict[str, Any]]:
        """Get server configuration info from /info.json"""
        try:
            data = await self._make_request('/info.json')
            if data and isinstance(data, dict):
                return {
                    'resources': data.get('resources', []),
                    'server': data.get('server', 'Unknown'),
                    'vars': data.get('vars', {}),
                    'icon': data.get('icon', ''),
                    'fallback': data.get('fallback', False),
                    'loadScreen': data.get('loadScreen', ''),
                    'enhancedHostSupport': data.get('enhancedHostSupport', False)
                }
            return None
            
        except Exception as e:
            logger.error(f"Error getting server info: {e}")
            return None
    
    async def get_server_status(self) -> Optional[Dict[str, Any]]:
        """Get server status from /dynamic.json"""
        try:
            start_time = datetime.now()
            data = await self._make_request('/dynamic.json')
            end_time = datetime.utcnow()
            
            if data and isinstance(data, dict):
                # Calculate ping from response time
                ping_ms = (end_time - start_time).total_seconds() * 1000
                
                # Extract server variables
                vars_data = data.get('vars', {})
                
                return {
                    'online': True,
                    'hostname': data.get('hostname', vars_data.get('sv_projectName', 'Motionlife RP')),
                    'clients': int(data.get('clients', 0)),
                    'maxClients': int(data.get('sv_maxclients', vars_data.get('sv_maxClients', 128))),
                    'mapname': data.get('mapname', 'San Andreas'),
                    'gametype': data.get('gametype', 'Roleplay'),
                    'serverVersion': data.get('server', 'Unknown'),
                    'ping': round(ping_ms, 2),
                    'vars': vars_data
                }
            else:
                return {
                    'online': False,
                    'hostname': 'Motionlife RP',
                    'clients': 0,
                    'maxClients': 128,
                    'mapname': 'San Andreas',
                    'gametype': 'Roleplay',
                    'serverVersion': 'Unknown',
                    'ping': 0,
                    'vars': {}
                }
                
        except Exception as e:
            logger.error(f"Error getting server status: {e}")
            return {
                'online': False,
                'hostname': 'Motionlife RP',
                'clients': 0,
                'maxClients': 128,
                'mapname': 'San Andreas',
                'gametype': 'Roleplay',
                'serverVersion': 'Unknown',
                'ping': 0,
                'vars': {}
            }
    
    async def get_players(self) -> Optional[List[Dict[str, Any]]]:
        """Get current players from /players.json"""
        try:
            data = await self._make_request('/players.json')
            
            if data and isinstance(data, list):
                players = []
                for player_data in data:
                    if isinstance(player_data, dict):
                        # Parse identifiers
                        identifiers = player_data.get('identifiers', [])
                        
                        # Extract useful identifiers
                        parsed_identifiers = {}
                        if isinstance(identifiers, list):
                            for identifier in identifiers:
                                if isinstance(identifier, str) and ':' in identifier:
                                    key, value = identifier.split(':', 1)
                                    parsed_identifiers[key] = value
                        
                        # Clean and validate player data
                        player_name = str(player_data.get('name', '')).strip()
                        if not player_name or player_name.lower() in ['unknown', '', 'null']:
                            continue
                        
                        player = {
                            'id': int(player_data.get('id', 0)),
                            'name': player_name,
                            'ping': int(player_data.get('ping', 0)),
                            'identifiers': identifiers,
                            'parsed_identifiers': parsed_identifiers,
                            'endpoint': player_data.get('endpoint', ''),
                            # Default values since they're not in the API
                            'job': 'civilian',
                            'role': 'civilian'
                        }
                        
                        players.append(player)
                
                logger.debug(f"Successfully parsed {len(players)} players")
                return players
            
            elif data == []:  # Empty array is valid
                logger.debug("No players online")
                return []
            
            else:
                logger.warning(f"Invalid players data format: {type(data)}")
                return []
            
        except Exception as e:
            logger.error(f"Error getting players: {e}")
            return []
    
    async def get_resources(self) -> Optional[List[str]]:
        """Get active server resources from /info.json"""
        try:
            info_data = await self.get_server_info()
            if info_data:
                resources = info_data.get('resources', [])
                if isinstance(resources, list):
                    return [str(r) for r in resources if r]
                return []
            return []
            
        except Exception as e:
            logger.error(f"Error getting resources: {e}")
            return []
    
    async def get_comprehensive_server_data(self) -> Optional[Dict[str, Any]]:
        """Get all server data in one call"""
        try:
            # Get status first (most important)
            status_data = await self.get_server_status()
            
            if not status_data or not status_data.get('online', False):
                # Server is offline
                return {
                    'online': False,
                    'hostname': 'Motionlife RP',
                    'clients': 0,
                    'maxClients': 128,
                    'players': [],
                    'resources': [],
                    'server_vars': {},
                    'timestamp': datetime.now().isoformat()
                }
            
            # Server is online, get additional data
            try:
                info_task = asyncio.create_task(self.get_server_info())
                players_task = asyncio.create_task(self.get_players())
                
                # Wait for both with timeout
                info_data, players_data = await asyncio.wait_for(
                    asyncio.gather(info_task, players_task, return_exceptions=True),
                    timeout=10.0
                )
                
                # Handle exceptions
                if isinstance(info_data, Exception):
                    logger.warning(f"Failed to get server info: {info_data}")
                    info_data = None
                    
                if isinstance(players_data, Exception):
                    logger.warning(f"Failed to get players: {players_data}")
                    players_data = []
                    
            except asyncio.TimeoutError:
                logger.warning("Timeout getting additional server data")
                info_data = None
                players_data = []
            
            return {
                **status_data,
                'players': players_data or [],
                'resources': info_data.get('resources', []) if info_data else [],
                'server_vars': info_data.get('vars', {}) if info_data else {},
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error getting comprehensive server data: {e}")
            return None
    
    async def test_connection(self) -> Dict[str, Any]:
        """Test API connection to all endpoints"""
        results = {
            'info': False,
            'dynamic': False,
            'players': False,
            'overall': False,
            'details': {}
        }
        
        # Test each endpoint
        endpoints = {
            'info': '/info.json',
            'dynamic': '/dynamic.json',
            'players': '/players.json'
        }
        
        for name, endpoint in endpoints.items():
            try:
                start_time = datetime.now()
                data = await self._make_request(endpoint)
                end_time = datetime.now()
                
                response_time = (end_time - start_time).total_seconds() * 1000
                
                if data is not None:
                    results[name] = True
                    results['details'][name] = {
                        'status': 'success',
                        'response_time_ms': round(response_time, 2),
                        'data_type': type(data).__name__,
                        'data_size': len(str(data)) if data else 0
                    }
                else:
                    results['details'][name] = {
                        'status': 'failed',
                        'response_time_ms': round(response_time, 2),
                        'error': 'No data returned'
                    }
                    
            except Exception as e:
                results['details'][name] = {
                    'status': 'error',
                    'error': str(e)
                }
        
        results['overall'] = any([results['info'], results['dynamic'], results['players']])
        
        return results
    
    async def close(self):
        """Close HTTP session"""
        if self.session and not self.session.closed:
            await self.session.close()
            logger.debug("FiveM API session closed")
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()