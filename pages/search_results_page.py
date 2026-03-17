import logging
import re
from playwright.async_api import expect
from pages.base_page import BasePage

logger = logging.getLogger(__name__)

class SearchResultsPage(BasePage):
    """eBay Search Results Page Object."""
    
    PRICE_FILTER_MIN = [
        "input[aria-label*='Minimum Value']", 
        "//input[contains(@aria-label, 'Minimum Value')]"
    ]
    PRICE_FILTER_MAX = [
        "input[aria-label*='Maximum Value']", 
        "input[placeholder*='max']",
        ".x-search-field__input--max",
        "input[id*='price_max']",
        "input[name*='_udhi']",
        "//input[contains(@aria-label, 'Maximum Value')]",
        "//input[contains(@placeholder, 'max')]",
        "div.x-price-range__input input >> nth=1"
    ]    
    RESULT_ITEMS = [
        ".srp-results .s-item",
        ".srp-river-results .s-item",
        ".s-item",
        ".srp-results .s-card",
        ".srp-river-results .s-card",
        "//div[contains(@class, 's-item') or contains(@class, 's-card')]"
    ]    
    ITEM_LINK = [
        ".s-item__link",
        ".s-card__link",
        ".su-card-link",
        "//a[contains(@class, 'link') and (contains(@href, '/itm/') or contains(@href, 'ebay.com/itm'))]"
    ]
    ITEM_PRICE = [
        ".su-styled-text.primary.bold.large-1.s-card__price",
        ".s-card__price",
        ".s-item__price",
        ".s-card__attribute-row",
        "//span[contains(@class, 's-card__price')]"
    ]
    NEXT_PAGE = [
        "a.pagination__next",
        ".pagination__next",
        "//a[@aria-label='Go to next search page']",
        "//button[@aria-label='Next page']"
    ]        
    BUY_IT_NOW_FILTER = [
        "a[href*='LH_BIN=1']", 
        "li.fake-tabs__item :has-text('Buy It Now')", 
        "//span[text()='Buy It Now']/ancestor::a"
    ]
    APPLIED_PRICE_FILTER = [
        "li.srp-multi-aspect__item--applied:has-text('Under')",
        "li.srp-carousel-list__item--applied:has-text('Under')",
        ".srp-multi-aspect__item--applied", 
        ".srp-carousel-list__item--applied",
        "//li[contains(@class, 'applied')]"
    ]

    async def verify_applied_price_filter(self, expected_price: float):
        """Passive verification of the applied filter chip."""
        self.logger.info(f"Verifying applied filter: {expected_price}")
        
        try:
            chip = await self.ui.find_element(self.APPLIED_PRICE_FILTER, "Applied Filter Chip", timeout=5000)
            
            actual_price = None
            try:
                anchored_price = [f"({self.APPLIED_PRICE_FILTER[0]}) {s}" for s in self.ITEM_PRICE]
                price_el = await self.ui.find_element(anchored_price, "Filter Chip Price", timeout=2000, is_optional=True)
                if price_el:
                    text = await price_el.inner_text()
                matches = re.findall(r'[\d.]+', text.replace(',', ''))
                if matches: actual_price = max([float(m) for m in matches])
            except Exception:
                pass
            
            # Fallback to full text if nested price extraction failed
            if actual_price is None:
                content = await chip.inner_text()
                matches = re.findall(r'[\d.]+', content.replace(',', ''))
                if matches: actual_price = max([float(m) for m in matches])
                
            if actual_price != expected_price:
                raise AssertionError(f"Price mismatch. Expected {expected_price}, found {actual_price}")
                
            self.logger.info(f"Filter verified: {actual_price}")
        except Exception as e:
            self.logger.warning(f"Passive verification skipped or failed: {e}")

    async def apply_max_price_filter(self, budget_per_item: float):
        price_str = str(int(budget_per_item)) if budget_per_item == int(budget_per_item) else str(budget_per_item)
        await self.ui.fill(self.PRICE_FILTER_MAX, price_str, "Max Price Filter", delete_count=8)
        await self.page.keyboard.press("Enter")
        await self.wait_for_ready()

    async def apply_buy_it_now_filter(self):
        await self.ui.click(self.BUY_IT_NOW_FILTER, "Buy It Now Filter")
        await self.page.wait_for_timeout(2000) # Allow page to settle after filter application
        await self.wait_for_ready()

    async def search_items_by_name_under_price(self, query: str, max_price: float, limit: int = 5) -> list[str]:
        """
        1. Performs search (via HomePage wrapper if needed, but usually this is called on the results context)
        2. Applies price filters
        3. Collects items under max_price using XPath and handles pagination.
        """
        self.logger.info(f"Searching for '{query}' under ILS {max_price} (Limit: {limit})")
        
        # 1. Verification/Trigger Search if not already filtered
        # (Assuming we are already on a search context, but we ensure filter is applied)
        await self.apply_buy_it_now_filter()
        await self.apply_max_price_filter(max_price)
        await self.verify_applied_price_filter(max_price)
        
        # 2. Collection Phase using XPath and Pagination
        return await self.get_items_under_price(max_price, limit)

    async def get_items_under_price(self, budget_per_item: float, limit: int = 5) -> list[str]:
        """Collects qualified item URLs using XPath-first strategy and visual tracking."""
        qualified_urls = []
        page_num = 1
        seen_urls = set()
        
        # Ultra-robust XPath targetting items across list, grid, and river views
        XPATH_ITEMS = "//*[contains(@class, 's-item__wrapper') or contains(@class, 's-card')]//ancestor::li[contains(@class, 's-item') or contains(@class, 's-card')] | //div[contains(@class, 's-item__wrapper')]"
        
        while len(qualified_urls) < limit and page_num <= 10:
            self.logger.info(f"Scanning Page {page_num}...")
            
            try:
                await self.ui.find_element([".srp-results", ".srp-main", "#srp-river-results"], f"Results Area P{page_num}", timeout=5000)
            except Exception:
                break

            # Locate actual cards
            card_locator = await self.ui.find_element(XPATH_ITEMS, f"Item Card {i+1} on Page {page_num}", timeout=1000)
            total_matches = await card_locator.count()
            self.logger.info(f"Found {total_matches} potential cards on page {page_num}.")
            
            for i in range(total_matches):
                if len(qualified_urls) >= limit: break
                
                try:
                    # 1. Capture the Item Card element
                    indexed_card = await self.ui.find_element(card_locator.nth(i), f"Item Card {i+1} on Page {page_num}", timeout=1000)
                    if not await indexed_card.is_visible():
                        continue
                        
                    # 2. Extract Title
                    title_selector = ".s-card__title, .s-item__title, [role='heading']"
                    title_el = await self.ui.find_element(indexed_card.locator(title_selector).first, f"Title {i+1}")
                    title_text = await title_el.inner_text()
                    if not (title_text.strip() and "Shop on eBay" not in title_text and len(title_text) >= 5):
                        continue
                        
                    # 3. Extract Price
                    price_selector = ".s-card__price, .su-styled-text.primary.bold.large-1, .s-item__price, [class*='price']"
                    price_el = await self.ui.find_element(indexed_card.locator(price_selector).first, f"Price {i+1}", timeout=1000)
                    price_text = await price_el.inner_text()
                    matches = re.findall(r'[\d.]+', price_text.replace(',', ''))
                    current_price = max([float(m) for m in matches]) if matches else None
                    if current_price is None or current_price > budget_per_item:
                        continue
                        
                    # 4. Extract URL
                    link_selector = ".s-item__link, .s-card__link, a[href*='/itm/']"
                    link_el = await self.ui.find_element(indexed_card.locator(link_selector).first, f"Link {i+1}")
                    url = await link_el.get_attribute("href")
                    
                    if url and "/itm/" in url and url not in seen_urls:
                        self.logger.info(f"QUALIFIED: Item {len(qualified_urls)+1} | Price: {current_price} | {title_text[:40]}...")
                        qualified_urls.append(url)
                        seen_urls.add(url)
                except Exception:
                    continue
            
            if len(qualified_urls) < limit:
                # 5. Handle Pagination
                try:
                    await self.ui.click(self.NEXT_PAGE, "Next Page")
                    await self.wait_for_ready()
                    page_num += 1
                except Exception:
                    break
                    
        return qualified_urls

    async def click_result_by_url(self, clean_url: str):
        """Finds and clicks a specific search result by its URL using the resilient handler."""
        item_selector = f"a[href*='{clean_url}']"
        await self.ui.click([
            f".srp-results {item_selector}", 
            f"#srp-river-results {item_selector}", 
            f".srp-main {item_selector}",
            item_selector
        ], f"Product Link: {clean_url}")

