import google.generativeai as genai
import logging
import time
import json
import aiohttp
import ssl
import certifi
from openai import OpenAI
from ...avatar.events import AvatarObserver
from ...avatar.models import Avatar

class CryptoAnalyzer(AvatarObserver):
    def __init__(self, config):
        self.dex_cache = {}
        self.cache_duration = 300  # 5 minutes
        self.session = None
        self.logger = logging.getLogger('CryptoAnalyzer.Core')
        self.perf_logger = logging.getLogger('CryptoAnalyzer.Performance')
        
        # Store the current analysis style and personality
        self._analysis_style = ""
        self._personality = ""
        
        # Initialize APIs using config
        genai.configure(api_key=config['api_keys']['gemini'])
        self.openai_client = OpenAI(api_key=config['api_keys']['openai'])

    def on_avatar_changed(self, avatar: Avatar) -> None:
        """Update analysis style and personality when avatar changes"""
        self._analysis_style = avatar.get_prompt('analysis')
        self._personality = avatar.get_prompt('personality')
        self.logger.info(f"Analysis style and personality updated for avatar: {avatar.name}")

    async def init_session(self):
        """Initialize or reinitialize the session if needed"""
        if self.session is None or self.session.closed:
            if self.session and self.session.closed:
                self.logger.debug("Previous session was closed, creating new session")
            
            # Configure SSL context with certifi certificates
            ssl_context = ssl.create_default_context(cafile=certifi.where())
            
            # Configure connection with SSL context
            connector = aiohttp.TCPConnector(
                ssl=ssl_context,
                limit=10,  # Connection pool limit
                ttl_dns_cache=300  # DNS cache TTL
            )
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                headers={
                    'User-Agent': 'CryptoAnalyzer/1.0',
                    'Accept': 'application/json'
                }
            )
            self.logger.debug("Initialized new aiohttp session with SSL context")
        return self.session

    async def close(self):
        """Close the aiohttp session"""
        if self.session and not self.session.closed:
            await self.session.close()
            self.session = None  # Set to None after closing
            self.logger.debug("Closed aiohttp session")

    async def get_dex_data(self, identifier):
        """Fetch data from DEXScreener using either ticker or contract address"""
        start_time = time.time()
        self.perf_logger.info(f"DEX_FETCH_START|identifier={identifier}")
        
        try:
            self.logger.info(f"Fetching DEXScreener data for: {identifier}")
            session = await self.init_session()  # Get a valid session

            # Clean the identifier (remove $ and whitespace)
            clean_identifier = identifier.replace('$', '').strip()
            url = f"https://api.dexscreener.com/latest/dex/search?q={clean_identifier}"
            
            self.logger.debug(f"Requesting URL: {url}")
            
            request_start = time.time()
            async with session.get(url) as response:
                request_duration = time.time() - request_start
                self.perf_logger.debug(f"DEX_API_REQUEST|duration={request_duration:.3f}s")
                
                if response.status != 200:
                    self.logger.error(f"DEXScreener API error: {response.status}")
                    self.perf_logger.error(f"DEX_FETCH_ERROR|identifier={identifier}|status={response.status}|duration={time.time()-start_time:.3f}s")
                    return None

                data = await response.json()
                pairs = data.get('pairs', [])
                
                self.logger.debug(f"Found {len(pairs)} total pairs in response")
                
                if not pairs:
                    self.logger.warning(f"No pairs found for {identifier}")
                    # Try fallback to contract address if no pairs found
                    fallback_url = f"https://api.dexscreener.com/latest/dex/tokens/{identifier}"
                    
                    fallback_start = time.time()
                    async with session.get(fallback_url) as fallback_response:
                        fallback_duration = time.time() - fallback_start
                        self.perf_logger.debug(f"DEX_FALLBACK_REQUEST|duration={fallback_duration:.3f}s")
                        
                        if fallback_response.status == 200:
                            fallback_data = await fallback_response.json()
                            pairs = fallback_data.get('pairs', [])
                            self.logger.debug(f"Fallback search found {len(pairs)} pairs")
                        if not pairs:
                            self.perf_logger.info(f"DEX_FETCH_END|identifier={identifier}|result=no_pairs|duration={time.time()-start_time:.3f}s")
                            return None

                # Filter and get valid pairs with liquidity
                valid_pairs = []
                total_liquidity = 0
                
                pairs_start = time.time()
                for pair in pairs:
                    liquidity_usd = pair.get('liquidity', {}).get('usd')
                    base_symbol = pair.get('baseToken', {}).get('symbol', '').upper()
                    quote_symbol = pair.get('quoteToken', {}).get('symbol', '').upper()
                    
                    self.logger.debug(f"Checking pair: {base_symbol}/{quote_symbol} - Liquidity: {liquidity_usd}")
                    
                    # Check if this pair matches our token (either as base or quote)
                    symbol_match = (base_symbol == clean_identifier.upper() or 
                                    quote_symbol == clean_identifier.upper())
                    
                    if (liquidity_usd and 
                        symbol_match and
                        pair.get('priceUsd') and 
                        pair.get('marketCap')):
                        try:
                            liq_float = float(liquidity_usd)
                            total_liquidity += liq_float
                            valid_pairs.append(pair)
                            self.logger.debug(
                                f"Added valid pair: {base_symbol}/{quote_symbol} "
                                f"on {pair['chainId']}, Liquidity: ${liq_float:,.2f}, "
                                f"Price: ${float(pair['priceUsd']):,.6f}"
                            )
                        except (ValueError, TypeError) as e:
                            self.logger.error(f"Error processing liquidity: {e}")
                            continue

                pairs_duration = time.time() - pairs_start
                self.perf_logger.debug(f"DEX_PAIRS_PROCESSING|pairs_count={len(pairs)}|valid_pairs={len(valid_pairs)}|duration={pairs_duration:.3f}s")

                if not valid_pairs:
                    self.logger.warning(
                        f"No valid pairs found for {identifier} after filtering"
                    )
                    self.perf_logger.info(f"DEX_FETCH_END|identifier={identifier}|result=no_valid_pairs|duration={time.time()-start_time:.3f}s")
                    return None

                # Get highest liquidity pair
                best_pair = max(valid_pairs, key=lambda x: float(x['liquidity']['usd']))
                
                self.logger.info(
                    f"Selected best pair for {identifier}: "
                    f"{best_pair['baseToken']['symbol']}/{best_pair['quoteToken']['symbol']} "
                    f"on {best_pair['chainId']} ({best_pair['dexId']}), "
                    f"Liquidity: ${float(best_pair['liquidity']['usd']):,.2f} "
                    f"({(float(best_pair['liquidity']['usd'])/total_liquidity*100):.1f}% of total liquidity)"
                )

                end_time = time.time()
                duration = end_time - start_time
                self.perf_logger.info(
                    f"DEX_FETCH_END|identifier={identifier}|"
                    f"chain={best_pair['chainId']}|"
                    f"dex={best_pair['dexId']}|"
                    f"liquidity=${float(best_pair['liquidity']['usd']):,.2f}|"
                    f"duration={duration:.3f}s"
                )
                return best_pair

        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            self.logger.error(f"Error in DEXScreener data fetch: {str(e)}", exc_info=True)
            self.perf_logger.error(f"DEX_FETCH_ERROR|identifier={identifier}|error={str(e)}|duration={duration:.3f}s")
            return None

    async def get_ai_analysis(self, analysis_data):
        """Get AI analysis using OpenAI GPT-4 with notification-optimized format."""
        start_time = time.time()
        self.perf_logger.info("OPENAI_ANALYSIS_START")
        
        try:
            self.logger.info("Starting OpenAI analysis")
            
            # Updated system prompt incorporating avatar personality and analysis style
            system_prompt = f"""You are an expert crypto analyst with the following personality and analysis style:

    PERSONALITY:
    {self._personality}

    ANALYSIS APPROACH:
    {self._analysis_style}

    Your goal is to provide a structured analysis in exactly this format:
    Write your analysis following the personality and approach described above. Determine if you should ape or you should hold a bit. Only reply with one choice and the symbol.

    ANALYSIS FOR [insert token ticker symbol]:

    🟢 Yes. I would ape! or 🔴 I would hold a bit
    [2 short sentences max]

    MC: $[value]

    Rules:
    • Use exact numeric values from the data
    • Use "N/A" for missing values
    - Don't include brackets around the token ticker symbol
    - Don't put specific numbers or symbols in the reason. The reason should be a normal alphabetical sentence without numbers or symbols
    • Use 🟢 for I would Ape, 🔴 for I would hold a bit and also put the word to the right of the symbol
    • Format must match exactly as shown
    """

            # Updated user prompt with minimal data structure
            user_prompt = f"""
    Here is the token data in JSON format (use only these values exactly):
    {json.dumps(analysis_data, indent=4)}

    Please provide analysis in the exact format specified, matching the template precisely.
    """

            # Make the API call
            completion = self.openai_client.chat.completions.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=0.7,
                max_tokens=200,
                top_p=0.9
            )
            
            if completion.choices:
                analysis = completion.choices[0].message.content.strip()
                self.logger.info(f"Generated analysis: {analysis}")
                
                end_time = time.time()
                total_duration = end_time - start_time
                self.perf_logger.info(f"OPENAI_ANALYSIS_END|status=completed|duration={total_duration:.3f}s")

                return analysis
            else:
                self.logger.error("No completion choices returned")
                self.perf_logger.error(f"OPENAI_ANALYSIS_ERROR|error=no_choices|duration={time.time()-start_time:.3f}s")
                return None

        except Exception as e:
            end_time = time.time()
            duration = end_time - start_time
            self.logger.error(f"Error in OpenAI analysis: {str(e)}", exc_info=True)
            self.perf_logger.error(f"OPENAI_ANALYSIS_ERROR|error={str(e)}|duration={duration:.3f}s")
            return None