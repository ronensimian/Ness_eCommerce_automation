import random
import logging
from pages.base_page import BasePage

logger = logging.getLogger(__name__)

class ProductPage(BasePage):
    """eBay Product Detail Page Object."""
    
    ADD_TO_CART = [
        "text='Add to cart'", 
        "a:has-text('Add to cart')",
        "#atcBtn_btn_1",
        "[id^='atcBtn_btn']",
        "internal:role=button[name=/add to cart/i]"
    ]
    ADD_TO_CART_CONFIRMED = [
        "//span[contains(text(), 'Added to cart')]",
        "//h2[contains(text(), 'Added to cart')]",
        ".header-title:has-text('Added to cart')",
        "#atc-overlay-title",
        ".vi-atc-notification-container"
    ]
    SEE_IN_CART = ["a[data-testid='ux-call-to-action'] span:has-text('See in cart')", "//a[contains(., 'See in cart')]"]
    VARIANTS = [
        "button[aria-haspopup='listbox']", 
        "select.x-msku__select-box",
        ".x-msku__select-box",
        "select[id*='msku']",
        "select[aria-label*='selection']",
        "select:not([style*='display: none'])"
    ]
    DROPDOWN_OPTIONS = [
        "select.x-msku__select-box", 
        "select[id*='msku']",
        "select[aria-label*='selection']",
        "select.msku-sel",
        "select:not([style*='display: none'])"
    ]
    SWATCH_OPTIONS = [
        "[data-testid='x-msku-evo'] div[role='button']:not([aria-disabled='true'])",
        ".x-msku__swatch-item:not(.x-msku__swatch-item--disabled)",
        "div.grid-swatch input + label",
        "ul.swatches-list li:not(.disabled) button"
    ]

    async def select_required_variants(self):
        """Standardizes variant selection logic for standard selects, custom listboxes, and swatches."""
        self.logger.info("Scanning for required product variants...")
        
        # 1. Handle standard Select dropdowns
        for base_sel in self.DROPDOWN_OPTIONS:
            for i in range(10):
                try:
                    indexed_sel = f":nth-match({base_sel}, {i + 1})"
                    sel_locator = await self.ui.find_element(indexed_sel, f"Dropdown {i + 1}", timeout=800, is_optional=True)
                    if not sel_locator: break
                    
                    # Target valid options (skip the 'Select' placeholder)
                    option_selector = f"{indexed_sel} >> option:not([value='-1']):not(:has-text('Select')):not(:has-text('Choose')):not(:has-text('Out of stock'))"
                    valid_options_count = await self.page.locator(option_selector).count()
                    
                    if valid_options_count > 0:
                        # Check if already selected (not "-1" or "Select")
                        current_val = await sel_locator.evaluate("el => el.value")
                        if current_val in ["-1", ""] or "select" in (await sel_locator.evaluate("el => el.options[el.selectedIndex].text")).lower():
                            target_idx = random.randint(0, valid_options_count - 1)
                            opt_locator = self.page.locator(option_selector).nth(target_idx)
                            await self.ui.find_element(opt_locator, f"Selected Option {target_idx + 1}")
                            target_val = await opt_locator.get_attribute("value")
                            await self.ui.select_option(indexed_sel, value=target_val, name=f"Variant Dropdown {i + 1}")
                            await self.page.wait_for_timeout(500)
                except Exception:
                    continue

        # 2. Handle Custom Evo Listboxes (Buttons that open menus)
        for base_sel in self.VARIANTS:
            if "select" in base_sel.lower(): continue
            for i in range(10):
                try:
                    indexed_btn = f":nth-match({base_sel}, {i + 1})"
                    btn = await self.ui.find_element(indexed_btn, f"Evo Button {i+1}", timeout=800, is_optional=True)
                    if not btn: break
                    
                    btn_text = (await btn.inner_text()).lower()
                    # If it says "Select", "Choose", or "None", we need to click it
                    unselected_patterns = ["select", "choose", "- none -", "selection"]
                    if any(p in btn_text for p in unselected_patterns):
                        self.logger.info(f"Opening listbox {i+1} ('{btn_text.strip()}')")
                        await self.ui.click(btn, f"Evo Button {i + 1} Click")
                        
                        listbox_id = await btn.get_attribute("aria-controls")
                        listbox_sel = f"#{listbox_id}" if listbox_id else ".listbox__options"
                        
                        try:
                            await self.ui.find_element(listbox_sel, "Listbox Menu", timeout=2000)
                        except Exception:
                            self.logger.debug(f"Listbox {listbox_sel} did not appear")
                            
                        potential_listboxes = []
                        if listbox_id: potential_listboxes.append(f"#{listbox_id}")
                        potential_listboxes.extend([".listbox__options", "[role='listbox']", ".msku-sel"])
                        
                        # Find the actual active listbox
                        active_listbox = await self.ui.find_element(potential_listboxes, "Active Listbox", timeout=2000, is_optional=True)
                        if not active_listbox:
                             self.logger.warning("Could not find any active listbox/menu.")
                             continue
                             
                        # Now find options WITHIN this listbox
                        opt_selector = ".listbox__option:not(:has-text('Select')):not(:has-text('Choose')):not(:has-text('Out of stock'))"
                        options_locator = active_listbox.locator(opt_selector)
                        
                        count = await options_locator.count()
                        self.logger.info(f"Listbox has {count} valid variations found.")
                        
                        if count > 0:
                            target_idx = random.randint(0, count - 1)
                            target_opt = options_locator.nth(target_idx)
                            
                            await self.ui.find_element(target_opt, f"Listbox Option {target_idx + 1}")
                            
                            # Log what we are selecting for better debugging
                            val_text = await target_opt.inner_text()
                            self.logger.info(f"Selecting variation: {val_text.strip()}")
                            
                            await target_opt.scroll_into_view_if_needed()
                            await target_opt.click()
                            await self.page.wait_for_timeout(1000)
                except Exception:
                    continue

        # 3. Handle Swatches/Buttons (Grid layouts)
        for base_sel in self.SWATCH_OPTIONS:
            try:
                swatch_locator = self.page.locator(base_sel)
                count = await swatch_locator.count()
                if count > 0:
                    # Check if any are already selected
                    selected_count = await self.page.locator(f"{base_sel}[aria-checked='true'], {base_sel}.selected").count()
                    if selected_count == 0:
                        self.logger.info(f"Picking a random swatch from {count} available.")
                        target_idx = random.randint(0, count - 1)
                        target_swatch = swatch_locator.nth(target_idx)
                        await target_swatch.scroll_into_view_if_needed()
                        await target_swatch.click()
                        await self.page.wait_for_timeout(800)
            except Exception:
                continue
        
        # Cleanup
        await self.page.keyboard.press("Escape")
        await self.page.wait_for_timeout(300)

    async def add_to_cart(self):
        """Orchestrates selecting variants, adding to cart, and verifying success."""
        await self.page.bring_to_front()
        await self.wait_for_ready()

        # Check if already in cart
        for selector in self.SEE_IN_CART:
            try:
                see_in_cart_locator = await self.ui.find_element(selector, f"Already in Cart Indicator ({selector})", timeout=1000, is_optional=True)
                if see_in_cart_locator:
                    self.logger.info("Item already in cart based on UI indicator. Skipping addition.")
                    return True # Treat as success since it's already there
            except Exception:
                pass

        # eBay sometimes requires multiple attempts if variants don't register
        for attempt in range(2):
            await self.select_required_variants()
            self.logger.info(f"Adding item to cart (Attempt {attempt+1})")
            await self.ui.click(self.ADD_TO_CART, "Add to Cart Button")
            
            # Verify success
            try:
                confirmation = await self.ui.find_element(self.ADD_TO_CART_CONFIRMED, "Confirmation", timeout=8000)
                text = (await confirmation.inner_text()).lower()
                if "added" in text or "cart" in text:
                    self.logger.info("Verification Success: Item added to cart.")
                    return True
            except Exception:
                self.logger.warning(f"Could not verify 'Added to cart' message on attempt {attempt+1}.")
                # If it's the first attempt, try to escape and retry
                await self.page.keyboard.press("Escape")
                await self.page.wait_for_timeout(1000)
        
        return False
