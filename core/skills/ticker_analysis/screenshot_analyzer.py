import logging
import time
import json
import google.generativeai as genai
from PIL import Image
from typing import Optional, Dict, Any
import re

class ScreenshotAnalyzer:
    def __init__(self, config):
        self.logger = logging.getLogger('CryptoAnalyzer.ScreenshotAnalyzer')
        genai.configure(api_key=config['api_keys']['gemini'])
        self.model = genai.GenerativeModel("gemini-2.0-flash-exp")
        
        # Statistical patterns to filter out from voice output
        self.stat_patterns = [
            r'MC:\s*\$?[\d,.]+',  # Matches MC: $123,456
            r'\d+(?:,\d{3})*(?:\.\d+)?[KMBTkmbt]?\s*(?:USD|ETH|BTC|\$)',  # Currency amounts
            r'(?:Volume|Liquidity|Cap):\s*[\d,.]+[KMBTkmbt]?',  # Volume/liquidity stats
            r'\d+(?:\.\d+)?%',  # Percentage values
            r'[A-F0-9]{40}',  # Contract addresses
            r'\$[A-Za-z]+:[A-F0-9-]+',  # Token identifiers
        ]

    def _is_stat_line(self, line: str) -> bool:
        """Check if a line contains statistical or numerical data."""
        combined_pattern = '|'.join(self.stat_patterns)
        return bool(re.search(combined_pattern, line))

    def _extract_voice_text(self, analysis_text: str) -> str:
        """Extract just the recommendation, reason and explanation for voice output"""
        try:
            # Split text into lines
            lines = analysis_text.split('\n')
            voice_lines = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                    
                # Keep lines that:
                # 1. Contain sentiment indicators (🟢, 🔴)
                # 2. Don't match our statistical patterns
                # 3. Aren't just numbers or symbols
                if ('🟢' in line or '🔴' in line or 
                    (not self._is_stat_line(line) and 
                     not line.strip().replace('$', '').replace('.', '').isdigit())):
                    voice_lines.append(line)
                    
                # Stop processing after finding statistical sections
                if self._is_stat_line(line):
                    break
                    
            return ' '.join(voice_lines).strip()
                
        except Exception as e:
            self.logger.error(f"Error extracting voice text: {str(e)}")
            return ""  # Return empty if error

    async def analyze_screenshot(self, image: Image.Image, crypto_analyzer, notification, voice_handler):
        """Analyze the captured screenshot with exact original functionality."""
        try:
            start_time = time.time()
            print("Starting image analysis with Gemini...")
            
            prompt = """
            Analyze this crypto-related image carefully and identify the MOST PROMINENT token mention and its exact pixel location in the image.
            Return ONLY ONE token - either the first one that appears or the one that appears most frequently.
            For this single token, extract:
            1. The full ticker symbol
            2. The complete sentence or paragraph it appears in
            3. Any nearby numbers, metrics, and important data
            4. Any contract addresses mentioned with it
            5. Any chain names or blockchain identifiers
            6. Any mentions of liquidity, volume, or market cap
            7. The exact pixel coordinates where the token symbol and price appear

            Also separately list:
            1. Any standalone contract addresses (0x...)
            2. Chain names mentioned
            3. Key metrics (price, mcap, volume, etc.)

            Format response as clean JSON with no formatting marks:
            {
                "tokens": [
                    {
                        "symbol": "$XYZ",
                        "context": "full sentence or paragraph containing the mention",
                        "metrics": ["list of relevant numbers/stats"],
                        "contract": "0x... if mentioned",
                        "chain": "chain name if mentioned",
                        "location": {
                            "x1": left position in pixels,
                            "y1": top position in pixels,
                            "x2": right position in pixels,
                            "y2": bottom position in pixels,
                            "price_location": {
                                "x1": left position of price in pixels,
                                "y1": top position of price in pixels,
                                "x2": right position of price in pixels,
                                "y2": bottom position of price in pixels
                            }
                        }
                    }
                ],
                "standalone_contracts": ["list of other 0x addresses"],
                "chains": ["list of chains"],
                "additional_metrics": {"metric": "value"}
            }

            Remember to return ONLY ONE token in the tokens array, choosing the most prominent or first-appearing one.
            Include BOTH the token symbol location and its associated price location in pixels relative to the image.
            Do not include any markdown formatting in the response.
            """
            
            print("Sending image to Gemini for analysis...")
            response = self.model.generate_content([prompt, image])
            print(f"Gemini analysis took {time.time() - start_time:.2f} seconds")
            
            try:
                print("Raw Gemini response:")
                response_text = response.text.strip()
                if response_text.startswith('```'):
                    response_text = response_text.replace('```json', '').replace('```', '').strip()

                extracted_data = json.loads(response_text)
                print("\nStructured data extracted:")
                print(json.dumps(extracted_data, indent=2))

                if extracted_data.get("tokens"):
                    print(f"Found {len(extracted_data['tokens'])} tokens to analyze")
                    
                if not extracted_data.get("tokens"):
                    print("No tokens or contracts found in image")
                    await crypto_analyzer.close()
                    return

                # Process tokens
                for token in extracted_data.get("tokens", []):
                    try:
                        symbol = token.get("symbol", "").replace("$", "").strip()
                        contract = token.get("contract")
                        
                        print(f"Analyzing token: {symbol}")
                        print(f"Context: {token.get('context')}")
                        print(f"Metrics found: {token.get('metrics')}")
                        
                        # Get market data
                        identifier = contract if contract else symbol
                        print(f"Fetching DEX data for {identifier}...")
                        
                        dex_data = await crypto_analyzer.get_dex_data(identifier)
                        if not dex_data:
                            print(f"No DEX data found for {symbol}")
                            continue
                        
                        print(f"DEX data found: {json.dumps(dex_data, indent=2)}")

                        # Prepare analysis data
                        analysis_data = {
                            'chain': dex_data['chainId'],
                            'price': dex_data['priceUsd'],
                            'marketCap': dex_data['marketCap'],
                            'volume24h': dex_data.get('volume', {}).get('h24'),
                            'liquidity': dex_data['liquidity']['usd'],
                            'price_change_24h': dex_data.get('priceChange', {}).get('h24'),
                            'buys24h': dex_data.get('txns', {}).get('h24', {}).get('buys'),
                            'sells24h': dex_data.get('txns', {}).get('h24', {}).get('sells'),
                            'original_context': token.get('context', ''),
                            'found_metrics': token.get('metrics', [])
                        }

                        if "location" in token:
                            print(f"Token location data found for {symbol}")
                        
                        # Get AI analysis
                        try:
                            print(f"Getting AI analysis for {symbol}...")
                            
                            ai_analysis = await crypto_analyzer.get_ai_analysis(analysis_data)
                            if ai_analysis:
                                print(f"\n{symbol} Final Analysis:")
                                print(ai_analysis)
                                
                                # Show full analysis in notification
                                notification.show_message(ai_analysis)
                                
                                # Only send recommendation and reason to voice
                                voice_text = self._extract_voice_text(ai_analysis)
                                if voice_text:
                                    await voice_handler.generate_and_play(voice_text, symbol)
                                
                            else:
                                print("No AI analysis generated")
                                
                        except Exception as e:
                            self.logger.error(f"AI analysis failed: {str(e)}")
                            print(f"AI analysis error: {str(e)}")
                            continue
                            
                    except Exception as e:
                        self.logger.error(f"Error processing token {symbol}: {str(e)}")
                        print(f"Token processing error: {str(e)}")
                        continue

            except json.JSONDecodeError as e:
                self.logger.error(f"JSON parsing error: {str(e)}")
                print("Failed to parse Gemini response as JSON:", str(e))

            # Cleanup
            try:
                await crypto_analyzer.close()
                crypto_analyzer.session = None
            except Exception as e:
                self.logger.error(f"Error closing session: {str(e)}")
                
            print("Analysis complete")
            
        except Exception as e:
            self.logger.error(f"Analysis error: {str(e)}", exc_info=True)
            print(f"Error: {str(e)}")
            try:
                await crypto_analyzer.close()
                crypto_analyzer.session = None
            except:
                pass