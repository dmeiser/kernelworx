"""Show & Sell Stage 1 page object — Units, invites, Unit Campaigns, roster, join.

Covers the browser surface the acceptance journey drives: the Unit list and its
create dialog, the Unit workspace tabs, the invite panel, invite redemption,
Unit Campaign create and close, the roster removal control, the join page, and
the admin-grant table.

Selector policy: the Stage 1 pages ship ``data-testid`` attributes and those are
the contract this run asserts.  Where an id is generated from an entity id
(``open-unit-<unitId>``, ``remove-member-<profileId>``) the suffix is read back
out of the DOM, so the page object never has to know an id in advance and a
mismatch fails as "the row is not there" rather than a timeout on a guessed
selector.  Confirm dialogs are committed by their action button, not by label:
the wording of a confirm is product copy and changes without warning.

Navigation reuses :meth:`BasePage.navigate`, which loads the SPA origin and
routes client-side; the deployed edge proxies ``/login`` and ``/l*`` to Cognito,
so deep-linking an authed route is not the pattern here.
"""

from __future__ import annotations

from playwright.sync_api import Locator, Page, expect

from .base_page import BasePage

#: Routes the journey opens.
UNIT_ROUTE = "/show-sell/units"
JOIN_ROUTE = "/show-sell/join"

# --- Units list -------------------------------------------------------------
ID_CREATE_UNIT = "create-unit"
ID_UNIT_LIST = "unit-list"
ID_INVITE_CODE_INPUT = "invite-code"
ID_REDEEM_INVITE = "redeem-invite"
ID_REDEEM_SUCCESS = "redeem-success"
PREFIX_OPEN_UNIT = "open-unit-"

#: The heading of the second-intent confirm ``createUnit`` raises when another Unit
#: already carries the same type, number, city, and state.
DUPLICATE_UNIT_HEADING = "A Unit with these details already exists"

# --- Unit workspace and Unit form ------------------------------------------
ID_TAB_SETTINGS = "tab-settings"
ID_TAB_ACCESS = "tab-access"
ID_TAB_CAMPAIGNS = "tab-campaigns"
ID_TAB_ROSTER = "tab-roster"
ID_UNIT_TYPE = "unit-type"
ID_UNIT_NUMBER = "unit-number"
ID_UNIT_CITY = "unit-city"
ID_UNIT_STATE = "unit-state"
ID_UNIT_DISPLAY_NAME = "unit-display-name"
ID_FORM_DIALOG_CONFIRM = "form-dialog-confirm"

# --- Invites and admin grants ----------------------------------------------
ID_CREATE_INVITE = "create-invite"
ID_ACTIVE_INVITE_COUNT = "active-invite-count"
ID_INVITE_CODE_VALUE = "invite-code-value"
PREFIX_INVITE_ROW = "invite-row-"
PREFIX_ADMIN_ROW = "admin-row-"
PREFIX_GRANT_REVOKE = "revoke-"

# --- Unit Campaigns --------------------------------------------------------
ID_CREATE_CAMPAIGN = "create-campaign"
ID_CAMPAIGN_NAME = "campaign-name"
ID_CREATED_CAMPAIGN_NOTE = "created-campaign-note"
ID_CREATED_JOIN_CODE = "created-join-code"
ID_ROSTER_COUNT = "roster-count"

# --- Stage 2: stock, Scout custody, Order fulfillment (§2.6) ----------------
# The workspace reaches these three screens through the tab buttons below.  Each screen's
# "opened" control is the one its body always renders — a count line or the panel's own primary
# button — because a tab that opened while its resolver failed looks identical until you ask for
# the number the screen itself claims.
ID_TAB_INVENTORY = "tab-inventory"
ID_TAB_CUSTODY = "tab-custody"
ID_TAB_ORDERS = "tab-orders"
ID_INVENTORY_COUNT = "position-count"
ID_CUSTODY_TOTAL = "custody-total"
ID_RECORD_CUSTODY_SALE = "record-custody-sale"
ID_FULFILLMENT_CAMPAIGN = "fulfillment-campaign"
ID_NO_ORDER_SELECTED = "no-order-selected-note"
PREFIX_INVENTORY_ROW = "position-row-"
PREFIX_CUSTODY_SCOUT_HELD = "custody-scout-held-"
PREFIX_ORDER_BLOCK = "order-block-"
PREFIX_LINE_ROW = "line-row-"
PREFIX_LINE_FULFILLED = "line-fulfilled-"
PREFIX_LINE_OWED = "line-owed-"

#: Tab button → a test id only that tab's screen renders.
STAGE_TWO_TAB_CONTROLS: dict[str, str] = {
    ID_TAB_INVENTORY: ID_INVENTORY_COUNT,
    ID_TAB_CUSTODY: ID_CUSTODY_TOTAL,
    ID_TAB_ORDERS: ID_RECORD_CUSTODY_SALE,
}

#: The §7 quantity a stock row answers, and the test-id stem that carries it
#: (``frontend/src/components/InventoryPanel.tsx``, ``PositionRow``).  The names are the SDL's,
#: so a GraphQL read and the screen can be compared key by key.
INVENTORY_COLUMNS: dict[str, str] = {
    "kernelPhysicalQty": "position-kernel-",
    "soldInPossessionQty": "position-sold-",
    "sellableKernelQty": "position-sellable-",
    "assignedOpenQty": "position-assigned-",
    "unassignedKernelQty": "position-unassigned-",
    "assignmentOverageQty": "position-overage-",
    "withScoutQty": "position-with-scout-",
    "totalUnitOwnedUndeliveredQty": "position-owned-",
    "councilOnOrderQty": "position-on-order-",
}
ID_JOIN_PROFILE_EMPTY = "join-profile-empty"
PREFIX_CAMPAIGN_ROW = "campaign-row-"
PREFIX_CAMPAIGN_STATUS = "campaign-status-"
PREFIX_ROSTER_LINK = "roster-"
PREFIX_CAMPAIGN_TOGGLE = "toggle-"
PREFIX_JOIN_CODE = "join-code-"
PREFIX_REVEAL_JOIN_CODE = "reveal-"
PREFIX_ROSTER_ROW = "roster-row-"
PREFIX_ROSTER_STATUS = "roster-status-"
PREFIX_REMOVE_MEMBER = "remove-member-"

# --- Join page -------------------------------------------------------------
ID_JOIN_CODE_INPUT = "join-code-input"
ID_JOIN_PROFILE = "join-profile"
ID_LOOKUP_JOIN_CODE = "lookup-join-code"
ID_JOIN_PREVIEW = "join-preview"
ID_SUBMIT_JOIN = "submit-join"
ID_JOIN_SUCCESS = "join-success"
PREFIX_JOIN_PROFILE_OPTION = "join-profile-option-"

#: Every surface that can show a live fixture code, as a CSS selector.
#:
#: Step screenshots mask these, and so does the failure screenshot: a 16-character
#: invite code on screen when a step stops is a credential-in-waiting, and pixels
#: cannot be redacted afterwards — ``redact_and_scan`` only reads text.  The
#: failure path has the raw page rather than a page object, so the selectors live
#: here, where both the locators and the failure masks come from one list.
CODE_MASK_SELECTORS: tuple[str, ...] = (
    "[data-testid='invite-code-value']",
    "[data-testid^='invite-row-']",
    # ``join-code`` (the campaign workspace card), ``join-code-<id>`` (the
    # campaigns list), and ``join-code-input`` (what the Scout typed).
    "[data-testid^='join-code']",
    "[data-testid='created-join-code']",
)


def code_mask_locators(page: Page) -> list[Locator]:
    """Return locators over every fixture-code surface *page* can show.

    Args:
        page: the page to mask.

    Returns:
        Locators over the invite and join code surfaces.
    """
    return [page.locator(selector) for selector in CODE_MASK_SELECTORS]


def profile_key(profile_id: str) -> str:
    """Return the comparable form of a profile id across its two spellings.

    ``listMyProfiles`` answers the storage spelling (``PROFILE#<uuid>``) while a
    roster row may answer the bare id — the same split as account ids, which come
    back as ``ACCOUNT#<sub>`` on one path and the bare sub on another.  Compared
    raw, the joined Scout reads as "not on the roster": an isolation assertion
    that fails on spelling rather than on access.
    """
    return profile_id.removeprefix("PROFILE#")


class ShowSellPage(BasePage):
    """Page object for the ``/show-sell/*`` routes.

    Args:
        page: Active Playwright :class:`~playwright.sync_api.Page`.
    """

    def __init__(self, page: Page) -> None:
        """Store the Playwright page.

        Args:
            page: Active Playwright page.
        """
        super().__init__(page)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _id_suffixes(self, prefix: str) -> list[str]:
        """Return every entity id whose element test id starts with *prefix*.

        Args:
            prefix: test id prefix, including its trailing separator.

        Returns:
            The suffixes, in document order.
        """
        return list(
            self.page.evaluate(
                """
                (prefix) => Array.from(document.querySelectorAll('[data-testid]'))
                    .map((element) => element.getAttribute('data-testid') || '')
                    .filter((value) => value.startsWith(prefix))
                    .map((value) => value.slice(prefix.length))
                """,
                prefix,
            )
        )

    def _fill_field(self, scope: Locator, test_id: str, value: str) -> None:
        """Type *value* into the input that a field's test id wraps.

        A MUI ``TextField`` puts props it does not consume on the form-control
        wrapper, so ``data-testid`` names the wrapper and the typeable element is
        the input inside it — filling the wrapper is a Playwright error.
        (Fields that want the id on the input itself use ``inputProps``; the join
        and invite code inputs do.)

        Args:
            scope: dialog or page to search.
            test_id: the shipped test id on the field wrapper.
            value: text to enter.
        """
        scope.get_by_test_id(test_id).locator("input").fill(value)

    def _combobox(self, scope: Locator, test_id: str) -> Locator:
        """Return the MUI control inside the field wrapper named *test_id*.

        Args:
            scope: dialog or page to search.
            test_id: the shipped test id on the field wrapper.

        Returns:
            The combobox that opens the menu.
        """
        return scope.get_by_test_id(test_id).locator('[role="combobox"]')

    def _combobox_by_label(self, scope: Locator, label_text: str) -> Locator:
        """Return the MUI Select control whose visible label contains *label_text*.

        Some shipped selects carry no test id at all, so the form control and its
        label are the only handle.  ``has-text`` is a substring match, which is
        what makes the component's own ``"Catalog *"`` spelling work — the same
        reach :mod:`pages.campaign_settings_page` uses for this component.

        Args:
            scope: dialog or page to search.
            label_text: text the visible label contains.

        Returns:
            The combobox that opens the menu.
        """
        return scope.locator(f'.MuiFormControl-root:has(label:has-text("{label_text}")) [role="combobox"]')

    def _confirm_open_dialog(self) -> None:
        """Commit the topmost dialog, by its action button.

        Every confirm in these screens renders *Cancel* first and the committing
        action last, so the position is stable while the label is product copy.
        ``.last`` matters: the duplicate-metadata confirmation opens on top of the
        create form, which stays mounted so the typed values survive, and a
        role locator over two dialogs is a strict-mode failure rather than a choice.
        """
        dialog = self.page.get_by_role("dialog").last
        expect(dialog).to_be_visible(timeout=10_000)
        dialog.locator("div.MuiDialogActions-root button").last.click()
        self.wait_for_loading()

    def open_tab(self, test_id: str) -> None:
        """Click a workspace tab and wait for its panel to settle.

        Args:
            test_id: one of ``tab-settings``, ``tab-access``, ``tab-campaigns``,
                ``tab-roster``, ``tab-catalog``.
        """
        self.page.get_by_test_id(test_id).click()
        self.wait_for_loading()

    # ------------------------------------------------------------------
    # Preview gate
    # ------------------------------------------------------------------

    def gate_opens(self, path: str, control_test_id: str) -> bool:
        """Return whether *path* stayed open or the gate redirected out of it.

        The gate renders nothing of its own — ``ShowSellRoutes`` answers an
        account outside the preview group with a redirect to the app root — so
        that redirect is the observable, and this reports it instead of failing.

        The control that proves the route *opened* belongs to the route: the
        Units list has ``create-unit``, the join page has ``lookup-join-code``.
        Probing one route for another's control reports a closed gate for an
        account that was admitted, which is the wrong answer in the direction
        that hides a broken gate.

        Args:
            path: Show & Sell route to open.
            control_test_id: a test id that only that route renders.

        Returns:
            ``True`` when the route's own controls are on screen, ``False``
            when the browser was redirected out of ``/show-sell``.
        """
        self.navigate(path)
        self.wait_for_loading()
        if "/show-sell" not in self.page.url:
            return False
        return self.page.get_by_test_id(control_test_id).count() > 0

    # ------------------------------------------------------------------
    # Units
    # ------------------------------------------------------------------

    def goto_units(self) -> None:
        """Open the Unit list, failing loudly if the gate closed it."""
        self.navigate(UNIT_ROUTE)
        self.wait_for_loading()
        expect(self.page.get_by_test_id(ID_CREATE_UNIT)).to_be_visible(timeout=15_000)

    def goto_unit(self, unit_id: str) -> None:
        """Open one Unit's workspace.

        The Unit Campaign roster lives on a different page, so a journey that has
        read a roster has to come back to the Unit before it can touch the
        campaigns or access tabs again.

        Args:
            unit_id: Unit to open.
        """
        self.navigate(f"{UNIT_ROUTE}/{unit_id}")
        self.wait_for_loading()
        expect(self.page.get_by_test_id(ID_TAB_SETTINGS)).to_be_visible(timeout=15_000)

    def open_unit(self, unit_id: str) -> None:
        """Open a Unit's workspace from the Unit list.

        Args:
            unit_id: Unit id.
        """
        self.page.get_by_test_id(f"open-unit-{unit_id}").click()
        self.wait_for_loading()

    def create_unit(
        self, *, unit_type: str, unit_number: str, city: str, state: str, display_name: str
    ) -> tuple[str, bool]:
        """Create a Unit through the create dialog and return its id.

        A Unit's tenant key is type, number, city, and state, so a re-run with the
        same four values is refused as a possible duplicate and the app asks a
        second time before creating a separate Unit.  That confirm arrives *after*
        the first click, on top of a create form that stays mounted, and the Unit
        list is already on screen underneath it — so racing "new row" against
        "duplicate confirm" resolves instantly on the list and hides the confirm.
        The row count is the outcome; the confirm is looked for on its own.

        Args:
            unit_type: one of Pack, Troop, Crew, Ships, District, Other.
            unit_number: Unit number as text.
            city: city name.
            state: two-letter state code (the field is a free-solo autocomplete).
            display_name: display name to store.

        Returns:
            ``(unit_id, duplicate_confirm_taken)`` — the second value says which
            branch the app answered, which is the difference between a new Unit and
            a deliberately separate duplicate.

        Raises:
            AssertionError: if no new row appeared, carrying whatever the page said.
        """
        known = set(self._id_suffixes(PREFIX_OPEN_UNIT))
        rows = self.page.locator(f"[data-testid^='{PREFIX_OPEN_UNIT}']")
        target = len(known) + 1
        self.page.get_by_test_id(ID_CREATE_UNIT).click()
        dialog = self.wait_for_dialog("Create a Unit")
        # MUI puts a ``data-testid`` it does not consume on the form-control root,
        # so the typeable control is the combobox inside it.  Scoped by test id
        # rather than accessible name: a MUI ``Select`` label is not always
        # exposed as the combobox's name, and the shipped id is the contract.
        self._combobox(dialog, ID_UNIT_TYPE).click()
        self.page.get_by_role("option", name=unit_type, exact=True).click()
        self._fill_field(dialog, ID_UNIT_NUMBER, unit_number)
        self._fill_field(dialog, ID_UNIT_CITY, city)
        # The state field is a free-solo Autocomplete, so filling its input is
        # what sets the value — no option has to be picked.
        self._fill_field(dialog, ID_UNIT_STATE, state)
        self._fill_field(dialog, ID_UNIT_DISPLAY_NAME, display_name)
        dialog.get_by_test_id(ID_FORM_DIALOG_CONFIRM).click()

        duplicate = self.page.get_by_text(DUPLICATE_UNIT_HEADING)
        duplicate_taken = False
        for attempt in range(1, 4):
            try:
                expect(rows).to_have_count(target, timeout=15_000)
                break
            except AssertionError as exc:
                if not duplicate_taken and duplicate.count() > 0:
                    self._confirm_open_dialog()
                    duplicate_taken = True
                    continue
                if attempt == 3:
                    said = self.page.locator("[role='alert']").all_inner_texts()
                    raise AssertionError(
                        f"no new Unit row appeared: expected {target} rows, the page said {said or 'nothing'}"
                    ) from exc

        new_ids = [candidate for candidate in self._id_suffixes(PREFIX_OPEN_UNIT) if candidate not in known]
        assert len(new_ids) == 1, f"expected exactly one new Unit row, saw {new_ids}"
        return new_ids[0], duplicate_taken

    # ------------------------------------------------------------------
    # Invites and admin grants
    # ------------------------------------------------------------------

    def create_invite(self) -> str:
        """Create a Unit invite and return its code.

        The code is read from the note the panel shows once, where the invite was
        created — the only surface guaranteed to carry it — and the row is then
        waited for rather than assumed: the panel refetches the list after the
        mutation, so reading it immediately races the refresh and reports "no new
        row" for an invite that exists.

        Returns:
            The 16-character code.  It is never transcribed by hand, so a typo
            cannot come back later as an "expired" invite.

        Raises:
            AssertionError: if the note never appears, or the code is not 16 characters.
        """
        self.page.get_by_test_id(ID_CREATE_INVITE).click()
        note = self.page.get_by_test_id(ID_INVITE_CODE_VALUE)
        expect(note).to_be_visible(timeout=20_000)
        code = note.inner_text().rsplit(":", 1)[-1].strip()
        assert len(code) == 16, f"expected a 16-character invite code, got {code!r}"
        expect(self.page.get_by_test_id(f"{PREFIX_INVITE_ROW}{code}")).to_be_visible(timeout=20_000)
        return code

    def redeem_invite(self, code: str) -> None:
        """Redeem a Unit invite from the Units page card.

        Args:
            code: the invite code.
        """
        self.page.get_by_test_id(ID_INVITE_CODE_INPUT).fill(code)
        self.page.get_by_test_id(ID_REDEEM_INVITE).click()
        expect(self.page.get_by_test_id(ID_REDEEM_SUCCESS)).to_be_visible(timeout=20_000)

    def admin_account_ids(self) -> list[str]:
        """Return the account ids in the Unit's admin-grant table.

        Returns:
            Account ids, in document order.
        """
        return self._id_suffixes(PREFIX_ADMIN_ROW)

    def revoke_admin_grant(self, account_id: str) -> None:
        """Revoke one admin grant and confirm.

        Args:
            account_id: the grantee's account id.
        """
        self.page.get_by_test_id(f"{PREFIX_GRANT_REVOKE}{account_id}").click()
        self._confirm_open_dialog()

    def wait_for_admin_grant_gone(self, account_id: str, *, attempts: int = 8) -> list[str]:
        """Return the grant table once *account_id* has no row, reloading between reads.

        Revoking writes the grant row and the panel refetches through an index, so
        the row can still be listed a moment later.  The reload is what re-runs the
        read, and ``tab-access`` is reopened because the workspace opens on its
        default tab.

        Args:
            account_id: the grantee's account id.
            attempts: how many reads to take before giving up.

        Returns:
            The grant rows as listed once *account_id* is gone.

        Raises:
            AssertionError: naming the rows every read showed.
        """
        rows: list[str] = []
        for attempt in range(attempts):
            rows = self.admin_account_ids()
            if account_id not in rows:
                return rows
            if attempt + 1 < attempts:
                self.page.reload(wait_until="networkidle")
                self.wait_for_loading()
                self.open_tab("tab-access")
        raise AssertionError(f"the grant table never dropped {account_id!r} in {attempts} reads; it shows {rows}")

    # ------------------------------------------------------------------
    # Unit Campaigns
    # ------------------------------------------------------------------

    def create_campaign(self, name: str, year: str, catalog_name: str) -> tuple[str, str]:
        """Create a Unit Campaign from the campaigns tab.

        The join code is read from the note the panel offers once, where the
        campaign was created: it is the only place the code is guaranteed to be
        shown, and reading it there avoids a second screen that renders it.

        Args:
            name: campaign name.
            year: campaign year as text.
            catalog_name: catalog to sell from, matched in the catalog menu.

        Returns:
            ``(unit_campaign_id, join_code)``.

        Raises:
            AssertionError: if no new campaign row appeared, or the code is not
                16 characters.
        """
        before = set(self._id_suffixes(PREFIX_CAMPAIGN_ROW))
        self.page.get_by_test_id(ID_CREATE_CAMPAIGN).click()
        dialog = self.wait_for_dialog("Create a campaign")
        self._fill_field(dialog, ID_CAMPAIGN_NAME, name)
        dialog.get_by_label("Campaign year").fill(year)
        # CatalogSelect ships no test id of its own, so it is reached the way
        # ``campaign_settings_page.py`` reaches the same component: the form
        # control whose label carries its text.  The component spells a required
        # label as ``"Catalog *"`` itself, and its entries are ``option``s in a
        # listbox mounted on the document body, so the dialog cannot scope those.
        self._combobox_by_label(dialog, "Catalog").click()
        listbox = self.page.get_by_role("listbox")
        # The component renders a disabled "Loading catalogs..." entry while the
        # catalogs load, so wait for exactly one entry with this name rather than
        # clicking whatever is on screen first.
        option = listbox.get_by_role("option", name=catalog_name)
        try:
            expect(option).to_have_count(1, timeout=15_000)
        except AssertionError as exc:
            offered = [text for text in listbox.get_by_role("option").all_inner_texts()]
            raise AssertionError(f"catalog {catalog_name!r} was not offered; the menu showed {offered}") from exc
        option.click()
        dialog.get_by_test_id(ID_FORM_DIALOG_CONFIRM).click()
        expect(self.page.get_by_test_id(ID_CREATED_CAMPAIGN_NOTE)).to_be_visible(timeout=20_000)

        # The panel refetches its own list after the mutation, so the row is waited
        # for by count rather than read from the list as it stands at this instant.
        rows = self.page.locator(f"[data-testid^='{PREFIX_CAMPAIGN_ROW}']")
        try:
            expect(rows).to_have_count(len(before) + 1, timeout=20_000)
        except AssertionError as exc:
            raise AssertionError(
                f"expected exactly one new campaign row: the panel shows {self._id_suffixes(PREFIX_CAMPAIGN_ROW)}"
            ) from exc
        new_ids = [campaign_id for campaign_id in self._id_suffixes(PREFIX_CAMPAIGN_ROW) if campaign_id not in before]
        assert len(new_ids) == 1, f"expected exactly one new campaign row, saw {new_ids}"
        join_code = self.page.get_by_test_id(ID_CREATED_JOIN_CODE).inner_text().strip()
        assert len(join_code) == 16, f"expected a 16-character join code, got {join_code!r}"
        return new_ids[0], join_code

    def campaign_status(self, campaign_id: str) -> str:
        """Return the status chip text on a campaign row.

        The chip is waited for by content, not visibility: the row can mount with
        an empty chip while the campaign read is still in flight, and reading that
        snapshot reports ``""`` for a campaign that is plainly Active a moment later.

        Args:
            campaign_id: Unit Campaign id.

        Returns:
            ``"Active"`` or ``"Closed"`` as rendered.
        """
        chip = self.page.get_by_test_id(f"{PREFIX_CAMPAIGN_STATUS}{campaign_id}")
        expect(chip).to_be_visible(timeout=15_000)
        expect(chip).not_to_have_text("", timeout=30_000)
        return chip.inner_text().strip()

    def wait_for_campaign_status(self, campaign_id: str, expected: str, *, timeout: int = 30_000) -> str:
        """Return the status chip once it reads *expected*.

        Toggling a Unit Campaign is a write followed by the panel's own refetch,
        so the chip on screen can still carry the old value a moment after the
        confirm.  ``expect`` polls the live DOM, which is the right wait here: no
        reload, because the campaigns list is a tab and a reload would land on
        the workspace's default tab instead.

        Args:
            campaign_id: Unit Campaign id.
            expected: ``"Active"`` or ``"Closed"``.
            timeout: how long to wait for the chip to change, in milliseconds.

        Returns:
            The chip text.
        """
        chip = self.page.get_by_test_id(f"{PREFIX_CAMPAIGN_STATUS}{campaign_id}")
        expect(chip).to_be_visible(timeout=15_000)
        try:
            expect(chip).to_have_text(expected, timeout=timeout)
        except AssertionError as exc:
            raise AssertionError(
                f"the Unit Campaign status chip never read {expected!r}; it reads {chip.inner_text().strip()!r}"
            ) from exc
        return chip.inner_text().strip()

    def close_campaign(self, campaign_id: str) -> None:
        """Close a Unit Campaign from the campaigns list and confirm.

        Args:
            campaign_id: Unit Campaign id.
        """
        self.page.get_by_test_id(f"{PREFIX_CAMPAIGN_TOGGLE}{campaign_id}").click()
        self._confirm_open_dialog()

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------

    def open_campaign_roster(self, campaign_id: str) -> None:
        """Open a Unit Campaign's roster from the campaigns list.

        Args:
            campaign_id: Unit Campaign id.
        """
        self.page.get_by_test_id(f"{PREFIX_ROSTER_LINK}{campaign_id}").click()
        self.wait_for_loading()
        expect(self.page.get_by_test_id(ID_ROSTER_COUNT)).to_be_visible(timeout=15_000)

    def roster_profile_ids(self) -> list[str]:
        """Return the profile ids with a roster row on screen.

        Returns:
            Profile ids, in document order.
        """
        return self._id_suffixes(PREFIX_ROSTER_ROW)

    def roster_row_key(self, profile_id: str) -> str:
        """Return the roster's own spelling of *profile_id*.

        Args:
            profile_id: the profile id from any source (storage or bare).

        Returns:
            The suffix of the matching ``roster-row-`` test id, which is what the
            removal control is named after.

        Raises:
            AssertionError: naming the rows the roster does show.
        """
        wanted = profile_key(profile_id)
        rows = self.roster_profile_ids()
        for row in rows:
            if profile_key(row) == wanted:
                return row
        raise AssertionError(f"the roster does not list profile {profile_id!r}; it shows {rows}")

    def wait_for_roster_row(self, profile_id: str, *, attempts: int = 8) -> list[str]:
        """Return the roster rows once *profile_id* is listed, reloading between reads.

        A join writes the roster row and the roster is read back through an index,
        so the row can be a moment late on screen.  Reloading is what re-runs the
        read: waiting on the page as it stands would wait on a response that is
        already finished.

        Args:
            profile_id: the profile id, in either spelling.
            attempts: how many reads to take before giving up.

        Returns:
            The roster rows as listed once *profile_id* appears.

        Raises:
            AssertionError: naming the rows every read showed.
        """
        wanted = profile_key(profile_id)
        rows: list[str] = []
        for _ in range(attempts):
            rows = self.roster_profile_ids()
            if any(profile_key(row) == wanted for row in rows):
                return rows
            self.page.reload(wait_until="networkidle")
            self.wait_for_loading()
        raise AssertionError(f"the roster never listed {profile_id!r} in {attempts} reads; it shows {rows}")

    def roster_can_remove(self, profile_id: str) -> bool:
        """Return whether *profile_id* still has an active, removable row.

        Args:
            profile_id: the profile id, in either spelling.
        """
        try:
            row = self.roster_row_key(profile_id)
        except AssertionError:
            return False
        return self.page.get_by_test_id(f"{PREFIX_REMOVE_MEMBER}{row}").count() > 0

    def remove_roster_member(self, profile_id: str) -> str:
        """Remove one Scout from the roster and confirm.

        Args:
            profile_id: the profile id, in either spelling.

        Returns:
            The roster's own spelling of that id, which is what the removal
            control and the row are named after.
        """
        row = self.roster_row_key(profile_id)
        self.page.get_by_test_id(f"{PREFIX_REMOVE_MEMBER}{row}").click()
        self._confirm_open_dialog()
        return row

    def roster_statuses(self, profile_id: str) -> list[str]:
        """Return the status chip text on every roster row naming *profile_id*.

        The chip reads ``Joined`` or ``Removed``; a removed row stays listed, so a
        row count alone cannot tell removal from a row that never changed.

        Args:
            profile_id: the profile id, in either spelling.
        """
        wanted = profile_key(profile_id)
        return [
            self.page.get_by_test_id(f"{PREFIX_ROSTER_STATUS}{row}").inner_text().strip()
            for row in self.roster_profile_ids()
            if profile_key(row) == wanted
        ]

    def wait_for_roster_removal(self, profile_id: str, *, attempts: int = 8) -> list[str]:
        """Return the roster's status chips for *profile_id* once removal reads back.

        The panel refetches through an index after the write, so the row can still
        read ``Joined`` and still carry its Remove button a moment later.  Both the
        chip and the button are waited for: the shipped panel shows
        ``remove-member-*`` only for an ACTIVE row with a guard version, so a row
        that still offers it has simply not been read as removed yet, and that is a
        stale read rather than a failed write.

        Args:
            profile_id: the profile id, in either spelling.
            attempts: how many reads to take before giving up.

        Returns:
            The status chip texts for that profile, once every one of them reads
            ``Removed``.

        Raises:
            AssertionError: naming what each read showed.
        """
        statuses: list[str] = []
        for _ in range(attempts):
            statuses = self.roster_statuses(profile_id)
            if statuses and all(status == "Removed" for status in statuses) and not self.roster_can_remove(profile_id):
                return statuses
            self.page.reload(wait_until="networkidle")
            self.wait_for_loading()
        raise AssertionError(
            f"the roster never read {profile_id!r} as Removed in {attempts} reads; "
            f"it reads {statuses} and still offers removal: {self.roster_can_remove(profile_id)}"
        )

    # ------------------------------------------------------------------
    # Join page
    # ------------------------------------------------------------------

    def goto_join(self) -> None:
        """Open the join page, failing loudly if the gate closed it."""
        self.navigate(JOIN_ROUTE)
        self.wait_for_loading()
        expect(self.page.get_by_test_id(ID_LOOKUP_JOIN_CODE)).to_be_visible(timeout=15_000)

    def join_unit_campaign(self, join_code: str, profile_id: str) -> str:
        """Look up a join code and join with one Scout campaign.

        The picker is read from the DOM rather than addressed by the id this run
        generated: ``listMyProfiles`` answers the storage spelling
        (``PROFILE#<uuid>``) and the join mutation answers the bare id, so the
        option is matched through :func:`profile_key` and the option's own suffix
        is what gets clicked and returned.

        Args:
            join_code: the Unit Campaign's join code.
            profile_id: the Scout profile whose campaign is joining.

        Returns:
            The profile id as the picker spells it.

        Raises:
            AssertionError: if the picker refuses to offer that profile — a
                profile with no current campaign has nothing to attach, which is
                a fixture problem and must say so.
        """
        self.page.get_by_test_id(ID_JOIN_CODE_INPUT).fill(join_code)
        self.page.get_by_test_id(ID_LOOKUP_JOIN_CODE).click()
        expect(self.page.get_by_test_id(ID_JOIN_PREVIEW)).to_be_visible(timeout=20_000)
        picker = self.page.get_by_test_id(ID_JOIN_PROFILE)
        expect(picker).to_be_visible(timeout=15_000)
        # The picker is a MUI Select: the test id sits on the field wrapper and
        # the control that opens the menu is the combobox inside it.
        self._combobox(self.page, ID_JOIN_PROFILE).click()
        if self.page.get_by_test_id(ID_JOIN_PROFILE_EMPTY).count() > 0:
            raise AssertionError("the join picker is empty: the Scout profile has no campaign to attach")
        wanted = profile_key(profile_id)
        offered = self._id_suffixes(PREFIX_JOIN_PROFILE_OPTION)
        matches = [suffix for suffix in offered if profile_key(suffix) == wanted]
        assert matches, f"the join picker does not offer {profile_id!r}; it offers {offered}"
        option = self.page.get_by_test_id(f"{PREFIX_JOIN_PROFILE_OPTION}{matches[0]}")
        expect(option).to_be_visible(timeout=10_000)
        # A profile with no current Scout Campaign is listed but disabled, and a
        # click on a disabled menu item is a timeout with no reason in it.
        assert option.get_attribute("aria-disabled") != "true", (
            f"the picker offers {profile_id!r} but disables it: that profile has no current Scout Campaign to attach"
        )
        option.click()
        self.page.get_by_test_id(ID_SUBMIT_JOIN).click()
        expect(self.page.get_by_test_id(ID_JOIN_SUCCESS)).to_be_visible(timeout=25_000)
        return matches[0]

    # ------------------------------------------------------------------
    # Stage 2: stock, Scout custody, Order fulfillment (§2.6 screens)
    # ------------------------------------------------------------------

    def goto_unit_campaign(self, unit_id: str, campaign_id: str) -> None:
        """Open one Unit Campaign workspace, where the Stage 2 screens live.

        Args:
            unit_id: the Unit that owns the campaign.
            campaign_id: the Unit Campaign to open.
        """
        self.navigate(f"{UNIT_ROUTE}/{unit_id}/campaigns/{campaign_id}")
        self.wait_for_loading()
        expect(self.page.get_by_test_id(ID_TAB_INVENTORY)).to_be_visible(timeout=15_000)

    def open_stage_two_tab(self, tab_test_id: str) -> None:
        """Open one Stage 2 tab and wait for the control only that screen renders.

        Args:
            tab_test_id: one of ``tab-inventory``, ``tab-custody``, ``tab-orders``.

        Raises:
            AssertionError: the tab is not a Stage 2 tab this page object knows.
        """
        control = STAGE_TWO_TAB_CONTROLS.get(tab_test_id)
        assert control is not None, f"{tab_test_id!r} is not a Stage 2 tab; known tabs: {sorted(STAGE_TWO_TAB_CONTROLS)}"
        self.open_tab(tab_test_id)
        expect(self.page.get_by_test_id(control)).to_be_visible(timeout=20_000)

    def _cell_text(self, stem: str, key: str) -> str:
        """Text of one Stage 2 cell, or an empty string when it is not on screen."""
        cell = self.page.get_by_test_id(f"{stem}{key}")
        return "" if cell.count() == 0 else (cell.first.inner_text() or "").strip()

    def _reopen_tab(self, tab_test_id: str, campaign_name: str | None = None) -> None:
        """Reload the workspace and reopen *tab_test_id*, the way a user would.

        Args:
            tab_test_id: the Stage 2 tab to reopen.
            campaign_name: a Scout Campaign to re-select afterwards.  The Order fulfillment tab
                keeps its Scout choice in component state, so a reload that is meant to refresh a
                read has to choose that Scout again — a waiter that reloads without re-choosing is
                waiting on a tab that was told to show nothing.
        """
        self.page.reload(wait_until="networkidle")
        self.wait_for_loading()
        self.open_stage_two_tab(tab_test_id)
        if campaign_name is not None:
            self.select_fulfillment_campaign(campaign_name)

    def _test_id_suffixes(self, prefix: str) -> list[str]:
        """Every test id on screen that starts with *prefix*, with the prefix removed.

        :meth:`_id_suffixes` is limited to ``div`` because the Stage 1 ids it reads are all
        divs; the Stage 2 screens key their ``<tr>`` rows and cells instead, so this one asks for
        any element.

        Args:
            prefix: test-id prefix to collect.

        Returns:
            The remaining part of each matching test id, in document order.
        """
        suffixes: list[str] = []
        for element in self.page.query_selector_all(f"[data-testid^='{prefix}']"):
            test_id = element.get_attribute("data-testid") or ""
            if test_id:
                suffixes.append(test_id[len(prefix) :])
        return suffixes

    def inventory_product_ids(self) -> list[str]:
        """Product ids with a stock row on the open Stock tab.

        Returns:
            Product ids, in document order.
        """
        return self._test_id_suffixes(PREFIX_INVENTORY_ROW)

    def wait_for_inventory_position(self, product_id: str, *, attempts: int = 8) -> dict[str, int]:
        """Return the open Stock tab's row for *product_id*, reloading until it appears.

        Every Stage 2 screen recomputes its numbers from the movement and balance rows on each
        read, and a write that just committed can still be missing from the first one, so the
        waiter reloads rather than reading once.  Giving up names the rows that *were* on screen,
        which is the difference between "the write did not land" and "the screen keys its rows
        differently than expected".

        Args:
            product_id: product whose position is wanted.
            attempts: how many reads to take before giving up.

        Returns:
            The §7 quantity names mapped to the numbers the screen shows.
        """
        seen: list[str] = []
        for attempt in range(attempts):
            seen = self.inventory_product_ids()
            if product_id in seen or any(row.endswith(product_id) for row in seen):
                row_key = next(row for row in seen if row == product_id or row.endswith(product_id))
                cells: dict[str, int] = {}
                for quantity, stem in INVENTORY_COLUMNS.items():
                    text = self._cell_text(stem, row_key)
                    if text:
                        cells[quantity] = int(text)
                return cells
            if attempt + 1 < attempts:
                self._reopen_tab(ID_TAB_INVENTORY)
        raise AssertionError(
            f"the Stock tab never showed a position row for {product_id!r} in {attempts} reads; "
            f"it shows {seen or 'no rows at all'}"
        )

    def select_fulfillment_campaign(self, campaign_name: str) -> None:
        """Choose the Scout Campaign the Order fulfillment tab lists Orders for.

        The tab starts with no Scout chosen and says so (``no-order-selected-note``): individual
        Orders belong to a Scout Campaign, so the panel will not guess which joined Scout's Orders
        to read (``frontend/src/components/OrderFulfillmentPanel.tsx``, ``CampaignPicker``).  The
        menu's option text is the Scout and campaign labels joined together, so the match is on
        the campaign name the lane chose — and the failure names the options that were offered.

        Args:
            campaign_name: the Scout Campaign's name, as the lane named it.
        """
        self.page.get_by_test_id(ID_FULFILLMENT_CAMPAIGN).click()
        listbox = self.page.get_by_role("listbox")
        expect(listbox).to_be_visible(timeout=10_000)
        options = listbox.locator('[role="option"]:not([aria-disabled="true"])')
        expect(options.first).to_be_visible(timeout=10_000)
        wanted = options.filter(has_text=campaign_name)
        if wanted.count() == 0:
            offered = [option.inner_text() for option in options.all()]
            raise AssertionError(
                f"the Order fulfillment tab's Scout picker does not offer {campaign_name!r}; it offers {offered}"
            )
        wanted.first.click()
        self.wait_for_loading()

    def fulfillment_notes(self) -> list[str]:
        """What the Order fulfillment tab says about having nothing to show, if anything."""
        notes = []
        for test_id in (ID_NO_ORDER_SELECTED, "no-campaign-note", "no-orders-note"):
            note = self.page.get_by_test_id(test_id)
            if note.count() > 0:
                notes.append(f"{test_id}: {(note.first.inner_text() or '').strip()}")
        return notes

    def custody_scout_totals(self) -> dict[str, int]:
        """Scout custody key to kernels held, from the open custody tab's Scout table.

        Returns:
            One entry per Scout row, keyed by the test id's own key so the caller can see how
            the screen groups a Scout's custody.
        """
        totals: dict[str, int] = {}
        for element in self.page.query_selector_all(f"[data-testid^='{PREFIX_CUSTODY_SCOUT_HELD}']"):
            test_id = element.get_attribute("data-testid") or ""
            text = (element.inner_text() or "").strip()
            if text:
                totals[test_id.removeprefix(PREFIX_CUSTODY_SCOUT_HELD)] = int(text)
        return totals

    def custody_line_test_ids(self) -> list[str]:
        """Every custody-line test id on the open custody tab, for a failure message."""
        return [f"custody-line{suffix}" for suffix in self._test_id_suffixes("custody-line-")]

    def wait_for_custody_held(self, profile_id: str, *, attempts: int = 8) -> int:
        """Return the custody tab's kernels held for *profile_id*, reloading until the row shows.

        The custody screen is the one place a Scout sees what it is carrying, and the number is
        recomputed from the custody rows on each read, so the waiter reloads rather than reading
        once — and gives up naming the rows it did see.

        Args:
            profile_id: the Scout's profile id, in any spelling.
            attempts: how many reads to take before giving up.

        Returns:
            Units in that Scout's custody across the campaign, as the screen states them.
        """
        wanted = profile_key(profile_id)
        seen: list[str] = []
        for attempt in range(attempts):
            totals = self.custody_scout_totals()
            seen = sorted(totals)
            for key, held in totals.items():
                if wanted and wanted in key:
                    return held
            if attempt + 1 < attempts:
                self._reopen_tab(ID_TAB_CUSTODY)
        raise AssertionError(
            f"the Scout custody tab never showed {profile_id!r} in {attempts} reads; it shows {seen}"
        )

    def custody_line_qty(self, profile_id: str, product_id: str) -> int | None:
        """Return the custody tab's per-line quantity for one Scout and product, if it shows one.

        Args:
            profile_id: the Scout's profile id, in any spelling.
            product_id: the product whose custody line is wanted.

        Returns:
            Units on that line, or ``None`` when the screen has no such line.
        """
        for suffix in self._test_id_suffixes("custody-line-qty-"):
            if profile_key(profile_id) in suffix and product_id in suffix:
                return int((self._cell_text("custody-line-qty-", suffix) or "0"))
        return None

    def wait_for_order_line(
        self,
        line_item_id: str,
        *,
        campaign_name: str | None = None,
        attempts: int = 8,
    ) -> tuple[int, int]:
        """Return the fulfillment tab's ``(fulfilled, still owed)`` for one line, reloading until it shows.

        Args:
            line_item_id: the line's id, which is also the row's key.
            campaign_name: the Scout Campaign to choose after each reload, for the same reason
                :meth:`_reopen_tab` takes it.
            attempts: how many reads to take before giving up.
        """
        seen: list[str] = []
        for attempt in range(attempts):
            seen = self._test_id_suffixes(PREFIX_LINE_ROW)
            if line_item_id in seen or any(row.endswith(line_item_id) for row in seen):
                return self.order_line_quantities(line_item_id)
            if attempt + 1 < attempts:
                self._reopen_tab(ID_TAB_ORDERS, campaign_name)
        raise AssertionError(
            f"the Order fulfillment tab never showed line {line_item_id!r} in {attempts} reads; "
            f"it shows lines {seen or 'none'} and says {self.fulfillment_notes() or 'nothing about being empty'}"
        )

    def order_line_quantities(self, line_item_id: str) -> tuple[int, int]:
        """Return ``(fulfilled, still owed)`` for one Order line on the open fulfillment tab.

        Args:
            line_item_id: the line's id, which is also the row's key.
        """
        fulfilled = self._cell_text(PREFIX_LINE_FULFILLED, line_item_id)
        owed = self._cell_text(PREFIX_LINE_OWED, line_item_id)
        assert fulfilled and owed, (
            f"the fulfillment tab shows no quantities for line {line_item_id!r}; "
            f"line cells on screen: {self._test_id_suffixes(PREFIX_LINE_FULFILLED)}"
        )
        return int(fulfilled), int(owed)

    def order_block_ids(self) -> list[str]:
        """Order ids with a block on the open Order fulfillment tab."""
        return self._test_id_suffixes(PREFIX_ORDER_BLOCK)

    def stage_two_notes(self) -> list[str]:
        """Return the guidance the Stage 2 screens are showing.

        The panels explain a refusal in place — a catalog mismatch between the two Campaigns, no
        eligible Scout, no orders yet — and that sentence is what tells the next reader whether a
        step stopped because of the build or because of the lane.
        """
        notes = []
        for test_id in ("catalog-mismatch-note", "no-campaign-note", "no-eligible-note", "no-orders-note"):
            note = self.page.get_by_test_id(test_id)
            if note.count() > 0:
                notes.append(f"{test_id}: {(note.first.inner_text() or '').strip()}")
        return notes

    # ------------------------------------------------------------------
    # Evidence masking
    # ------------------------------------------------------------------

    def code_mask_locators(self) -> list[Locator]:
        """Return locators for fixture codes that must not reach evidence.

        Playwright masks whatever a locator matches and ignores what is not on
        screen, so one list covers every code-bearing surface the journey opens.

        Returns:
            Locators over the invite and join code surfaces.
        """
        return code_mask_locators(self.page)
