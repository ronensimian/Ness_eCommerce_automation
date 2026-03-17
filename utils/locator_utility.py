import logging
import os
import random
import uuid
from datetime import datetime
from typing import List, Optional
from playwright.async_api import Page, Locator, expect

logger = logging.getLogger(__name__)

class UIActionHandler:
    """Resilient UI interaction handler."""
    
    DEFAULT_TIMEOUT = 3000  # ms
    RETRY_TIMEOUT = 1000    # ms for fallback check
    
    def __init__(self, page: Page):
        self.page = page

    async def check_for_captcha(self):
        """
        Detects if a CAPTCHA or 'Security Measure' page is visible.
        If found, it logs a warning and waits, allowing a developer to solve it manually.
        """
        captcha_indicators = [
            "text='Please verify you are a human'",
            "text='Security Check'",
            "iframe[src*='captcha']",
            "text='verify you\\'re not a robot'",
            "id='captcha-container'"
        ]

        for indicator in captcha_indicators:
            try:
                # Use highlight directly to avoid infinite recursion with find_element
                locator = self.page.locator(indicator).first
                if await locator.is_visible():
                    await self.highlight_element_and_capture_screenshot(locator, "Bot Detection Indicator")
                    logger.warning("Pausing for up to 60 seconds. PLEASE SOLVE CAPTCHA MANUALLY IF NEEDED.")
                    
                    # Wait for it to disappear (user solves it) or timeout
                    for _ in range(60):
                        if not await locator.is_visible():
                            logger.info("Captcha resolved! Proceeding...")
                            return
                        await self.page.wait_for_timeout(1000)
            except Exception:
                continue

    async def breathe(self, min_ms=100, max_ms=500):
        """Adds a slight randomized delay to mimic human reading/decision time."""
        delay = random.randint(min_ms, max_ms)
        await self.page.wait_for_timeout(delay)

    async def highlight_element_and_capture_screenshot(self, locator: Locator, name: str = "element"):
        """Captures a screenshot with a red frame around the specified element."""
        try:
            # 1. Apply Highlight (User requirement: 'Red frame for every element')
            try:
                await locator.evaluate("""el => {
                    el.style.setProperty('outline', '4px solid red', 'important');
                    el.style.setProperty('outline-offset', '-4px', 'important');
                    el.style.setProperty('z-index', '1000000', 'important');
                }""")
            except Exception as e:
                logger.debug(f"Failed to apply highlight to {name}: {e}")
 
            # Capture Screenshot with pure timestamp as name
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
            filename = f"{timestamp}.png"
            
            target_dir = getattr(self.page, "screenshot_dir", os.path.join("results", "screenshots"))
            os.makedirs(target_dir, exist_ok=True)
            path = os.path.join(target_dir, filename)
            
            await self.page.screenshot(path=path, full_page=False)
            logger.info(f"Visual checkpoint captured for '{name}': {path}")
            
            # Repaint delay
            await self.page.wait_for_timeout(500)

            # 3. Clean up Highlight (User requested to remove it after screenshot)
            try:
                await locator.evaluate("""el => {
                    el.style.removeProperty('outline');
                    el.style.removeProperty('outline-offset');
                    el.style.removeProperty('z-index');
                }""")
            except Exception:
                pass
            
        except Exception as e:
            logger.debug(f"Highlight/Screenshot skipped for '{name}': {e}")

    async def find_element(self, selectors: List[str] | str | Locator, name: str = "element", timeout: int = DEFAULT_TIMEOUT, is_optional: bool = False) -> Optional[Locator]:
        """Attempts to find an element using fallback selectors."""
        if isinstance(selectors, Locator):
            try:
                await self.highlight_element_and_capture_screenshot(selectors, name)
                return selectors
            except Exception:
                if is_optional: return None
                raise

        # 2. Normalize selectors to a list
        if isinstance(selectors, str):
            selectors = [selectors]
            
        # 3. Always check for blockers before searching
        await self.check_for_captcha()
        
        last_error = RuntimeError(f"No selectors provided for {name}")
        total_selectors = len(selectors)
        for i, selector in enumerate(selectors):
            current_try = i + 1
            try:
                locator = self.page.locator(selector).first
                # Wait for the element to be visible before highlighting/returning
                current_timeout = timeout if i == 0 else self.RETRY_TIMEOUT
                await locator.wait_for(state="visible", timeout=current_timeout)
                    
                # Visual detection checkpoint - centers and highlights element
                await self.highlight_element_and_capture_screenshot(locator, name)
                
                logger.info(f"SUCCESS: Found '{name}' (Attempt {current_try}/{total_selectors})")
                return locator
            except Exception as e:
                if is_optional:
                    logger.debug(f"Optional element '{name}' not found on attempt {current_try}/{total_selectors}")
                else:
                    logger.warning(f"ATTEMPT {current_try}/{total_selectors} FAILED for '{name}' using: {selector}")
                last_error = e

        if is_optional:
            logger.info(f"NOTICE: Optional element '{name}' not detected after all attempts.")
            return None
            
        logger.error(f"FATAL: All selectors failed for '{name}'.")
        raise last_error

    async def click(self, selectors: List[str] | str, name: str = "element"):
        """Clicks an element with resilience."""
        try:
            locator = await self.find_element(selectors, name)
            await locator.click(timeout=self.RETRY_TIMEOUT)
        except Exception as e:
            logger.warning(f"Initial click failed or intercepted for '{name}': {e}. Attempting recovery/forced click.")
            locator = await self.find_element(selectors, name)
            await locator.click(force=True)
            
        logger.info(f"Clicked '{name}'")

    async def fill(self, selectors: List[str] | str, value: str, name: str = "element", delete_count: int = 0):
        """Fills an input with resilience."""
        locator = await self.find_element(selectors, name)
        await locator.click()
        await locator.clear()
        
        if delete_count > 0:
            logger.info(f"Performing {delete_count} manual clear actions for '{name}'")
            for _ in range(delete_count):
                await self.page.keyboard.press("Delete")
                await self.page.keyboard.press("Backspace")
            await self.page.wait_for_timeout(500)   
            
        await locator.fill(value)
        logger.info(f"Filled '{name}' with value: {value}")

    async def select_option(self, selectors: List[str] | str, value: str = None, label: str = None, index: int = None, name: str = "dropdown"):
        """Selects an option from a dropdown."""
        locator = await self.find_element(selectors, name)
        
        # Highlight before selection
        await self.highlight_element_and_capture_screenshot(locator, f"{name} before selection")
        
        if value is not None:
            await locator.select_option(value=value)
        elif label is not None:
            await locator.select_option(label=label)
        elif index is not None:
            await locator.select_option(index=index)
            
        logger.info(f"Selected option in '{name}'")
        # Optional: Highlight after selection to show state
        await self.highlight_element_and_capture_screenshot(locator, f"{name} after selection")
