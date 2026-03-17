import re
import logging
from pages.base_page import BasePage

logger = logging.getLogger(__name__)

class CartPage(BasePage):
    """eBay Cart Page Object."""
    
    CART_TOTAL = [
        "div[data-test-id='SUBTOTAL']",
        "//div[@data-test-id='SUBTOTAL']",
        ".cart-summary-line-item__value",
        ".app-cart-summary__total-value",
        "[class*='subtotal']",
        "//span[contains(text(), 'Subtotal')]/following::span[1]"
    ]

    CART_ITEM_COUNT = [
        "div[data-test-id='cart-summary'] .cart-summary-line-item:first-child .text-display-span"
    ]

    async def get_item_count(self) -> int:
        """Extracts the number of items currently in the cart."""
        try:
            locator = await self.ui.find_element(self.CART_ITEM_COUNT, "Cart Item Count", timeout=3000, is_optional=True)
            text = await locator.inner_text()
            # Look for digits in text like "Cart (3 items)" or "3 items"
            match = re.search(r'(\d+)', text)
            if match:
                count = int(match.group(1))
                self.logger.info(f"Detected {count} items in cart via header.")
                return count
        except Exception:
            self.logger.warning("Could not clearly detect item count in cart header.")
        return 0

    async def get_cart_total(self) -> float:
        """Extracts the numeric subtotal from the cart page."""
        locator = await self.ui.find_element(self.CART_TOTAL, "Cart Total Subtotal")
        total_text = await locator.inner_text()
        
        # Robust extraction using regex
        match = re.search(r'[\d,.]+', total_text.replace(',', ''))
        if not match:
            self.logger.error(f"Could not parse cart total from text: {total_text}")
            return 0.0
            
        total_val = float(match.group().replace(',', ''))
        self.logger.info(f"Extracted cart total: {total_val}")
        return total_val

    async def assertCartTotalNotExceeds(self, budget_per_item: float, items_count: int) -> None:
        """
        Verifies the shopping cart amount and item count.
        """
        # 1. Open the shopping cart
        await self.navigate("https://cart.ebay.com")
        await self.wait_for_ready()

        # 2. Verify item count
        actual_count = await self.get_item_count()
        if actual_count > 0 and actual_count != items_count:
            self.logger.error(f"ITEM COUNT MISMATCH: Expected {items_count}, but found {actual_count}")
            # We don't raise yet, as subtotal check is primary, but we log it heavily.
        
        # 3. Read the total amount
        total = await self.get_cart_total()

        # 4. Calculate threshold
        threshold = items_count * budget_per_item
        
        self.logger.info(f"Cart Verification: Total={total}, Threshold={threshold} ({items_count} items * ILS {budget_per_item})")
        
        # 5. Verify total and count
        # If count detection failed (actual_count=0) but we have a total, we still check the count if it was found
        if items_count > 0 and actual_count == 0 and total == 0:
             raise AssertionError(f"Cart appears EMPTY! Expected {items_count} items.")
             
        if actual_count > 0 and actual_count != items_count:
             raise AssertionError(f"ITEM COUNT MISMATCH: Expected {items_count}, but found {actual_count}")
             
        if total > threshold:
            raise AssertionError(f"Cart total {total} exceeds the calculated threshold of {threshold}")
            
        self.logger.info("Verification Success: Cart matches expected criteria.")
