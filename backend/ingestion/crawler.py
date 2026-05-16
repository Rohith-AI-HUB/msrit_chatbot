import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import urljoin
from urllib.parse import urlparse

import requests

from bs4 import BeautifulSoup

from app.core.config import settings
from app.core.logging import setup_logger


logger = setup_logger("crawler")


class MSRITCrawler:

    BASE_URL = "https://www.msrit.edu"

    START_URLS = [
        "https://www.msrit.edu/",
        "https://www.msrit.edu/admissions.html",
        "https://www.msrit.edu/placement.html",
        "https://www.msrit.edu/facilities.html",
        "https://www.msrit.edu/departments.html",
    ]

    EXCLUDED_PATTERNS = [
        "/gb/",
        "chairman",
        "principal-advisor",
        "governing-body",
        "board-of-management",
        "news-events",
        "tender",
        "circular",
    ]

    IMPORTANT_KEYWORDS = [
        "naac",
        "nba",
        "nirf",
        "accreditation",
        "ranking",
        "department",
        "admission",
        "placement",
        "faculty",
        "hostel",
        "course",
        "program",
        "engineering",
        "research",
        "m.tech",
        "mba",
        "mca",
    ]

    GOOGLE_SHEET_ID = (
        "1afTdPh2inIFFB471lu4jIzrv3alswZUrcltVGqu82MY"
    )

    def __init__(self):

        self.visited = set()

        self.to_visit = deque(
            self.START_URLS
        )

        self.documents = []

    # ==========================================
    # Faculty Sheet
    # ==========================================
    def fetch_google_sheet_rows(
        self
    ) -> list[dict]:

        logger.info(
            "Fetching faculty sheet"
        )

        url = (
            f"https://docs.google.com/"
            f"spreadsheets/d/"
            f"{self.GOOGLE_SHEET_ID}/gviz/tq"
            f"?tqx=out:json&tq=select%20*&gid=0"
        )

        response = requests.get(
            url,
            timeout=settings.REQUEST_TIMEOUT
        )

        response.raise_for_status()

        match = re.search(
            (
                r"google\.visualization"
                r"\.Query\.setResponse"
                r"\((.*)\);?$"
            ),
            response.text,
            re.S,
        )

        if not match:

            logger.warning(
                "Could not parse faculty sheet"
            )

            return []

        data = json.loads(
            match.group(1)
        )

        columns = [
            (
                column.get("label")
                or column.get("id")
            )
            for column in (
                data["table"]["cols"]
            )
        ]

        rows = []

        for row in data["table"]["rows"]:

            values = [
                (
                    cell.get("v")
                    if cell
                    else ""
                )
                for cell in row["c"]
            ]

            rows.append(
                dict(
                    zip(columns, values)
                )
            )

        logger.info(
            f"Loaded {len(rows)} "
            f"faculty rows"
        )

        return rows

    def add_cse_faculty_document(
        self
    ):

        rows = (
            self.fetch_google_sheet_rows()
        )

        faculty_lines = [
            "Computer Science and Engineering Faculty",
            "CSE Department Faculty List",
        ]

        for row in rows:

            name = str(
                row.get(
                    "Faculty_Full_Name"
                )
                or ""
            ).strip()

            if not name:
                continue

            designation = str(
                row.get(
                    "Current_designation"
                )
                or ""
            ).strip()

            qualification = str(
                row.get(
                    "Highest_Qualification"
                )
                or ""
            ).strip()

            email = str(
                row.get(
                    "Email_Address"
                )
                or ""
            ).strip()

            details = [name]

            if designation:
                details.append(
                    designation
                )

            if qualification:
                details.append(
                    qualification
                )

            if email:
                details.append(email)

            faculty_lines.append(
                " | ".join(details)
            )

        self.documents.append({
            "url": (
                "https://www.msrit.edu/"
                "department/faculty.html"
            ),
            "content": "\n".join(
                faculty_lines
            )
        })

        logger.info(
            "Added faculty document"
        )

    # ==========================================
    # Content Cleaning
    # ==========================================
    @classmethod
    def clean_page_content(
        cls,
        soup: BeautifulSoup
    ) -> str:

        for tag in soup([
            "script",
            "style",
            "nav",
            "footer",
            "header",
            "noscript",
            "svg",
        ]):
            tag.decompose()

        sections = []

        elements = soup.find_all([
            "h1",
            "h2",
            "h3",
            "h4",
            "p",
            "li",
        ])

        for element in elements:

            text = " ".join(
                element.get_text(
                    " ",
                    strip=True
                ).split()
            )

            if len(text) < 25:
                continue

            lower_text = text.lower()

            # Skip generic junk
            junk_patterns = [
                "click here",
                "read more",
                "copyright",
                "all rights reserved",
                "home",
                "back",
            ]

            if any(
                pattern in lower_text
                for pattern in junk_patterns
            ):
                continue

            # Keep important academic content
            if any(
                keyword in lower_text
                for keyword
                in cls.IMPORTANT_KEYWORDS
            ):

                sections.append(text)

                continue

            # Keep sufficiently large paragraphs
            if len(text) > 120:

                sections.append(text)

        return "\n\n".join(sections)

    # ==========================================
    # URL Filtering
    # ==========================================
    @classmethod
    def is_valid_url(
        cls,
        url: str
    ) -> bool:

        parsed = urlparse(url)

        if (
            "msrit.edu"
            not in parsed.netloc
        ):
            return False

        url_lower = url.lower()

        invalid_patterns = [
            "#",
            "javascript:",
            "mailto:",
            ".pdf",
            ".jpg",
            ".png",
            ".jpeg",
            ".zip",
        ]

        if any(
            pattern in url_lower
            for pattern
            in invalid_patterns
        ):
            return False

        if any(
            pattern in url_lower
            for pattern
            in cls.EXCLUDED_PATTERNS
        ):
            return False

        return True

    # ==========================================
    # Crawl
    # ==========================================
    def crawl(self):

        logger.info(
            "Starting crawl"
        )

        while self.to_visit:

            if (
                len(self.visited)
                >= settings.MAX_CRAWL_PAGES
            ):

                logger.warning(
                    "Reached crawl limit"
                )

                break

            url = self.to_visit.popleft()

            if url in self.visited:
                continue

            logger.info(
                f"Crawling: {url}"
            )

            self.visited.add(url)

            try:

                response = requests.get(
                    url,
                    timeout=settings.REQUEST_TIMEOUT
                )

                if (
                    response.status_code
                    != 200
                ):

                    logger.warning(
                        f"Skipping {url}"
                    )

                    continue

                soup = BeautifulSoup(
                    response.text,
                    "html.parser"
                )

                cleaned_content = (
                    self.clean_page_content(
                        soup
                    )
                )

                if (
                    len(cleaned_content)
                    > 150
                ):

                    self.documents.append({
                        "url": url,
                        "content": (
                            cleaned_content
                        )
                    })

                # Extract links
                for link in soup.find_all(
                    "a",
                    href=True
                ):

                    href = link["href"]

                    full_url = urljoin(
                        self.BASE_URL,
                        href
                    )

                    if not self.is_valid_url(
                        full_url
                    ):
                        continue

                    if (
                        full_url
                        not in self.visited
                    ):

                        self.to_visit.append(
                            full_url
                        )

            except Exception as e:

                logger.exception(
                    f"Failed to crawl "
                    f"{url}: {e}"
                )

        logger.info(
            f"Crawled "
            f"{len(self.visited)} pages"
        )

    # ==========================================
    # Save Documents
    # ==========================================
    def save_documents(self):

        output_path = Path(
            settings.RAW_DATA_PATH
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        unique_documents = []

        seen = set()

        for doc in self.documents:

            key = (
                doc["url"],
                doc["content"]
            )

            if key not in seen:

                seen.add(key)

                unique_documents.append(doc)

        logger.info(
            f"Saving "
            f"{len(unique_documents)} "
            f"documents"
        )

        with open(
            output_path,
            "w",
            encoding="utf-8"
        ) as file:

            for doc in unique_documents:

                file.write(
                    f"PAGE_URL: "
                    f"{doc['url']}\n\n"
                )

                file.write(
                    "CONTENT:\n"
                )

                file.write(
                    f"{doc['content']}\n\n"
                )

        logger.info(
            "Documents saved"
        )

    # ==========================================
    # Run Pipeline
    # ==========================================
    def run(self):

        self.crawl()

        self.add_cse_faculty_document()

        self.save_documents()

        logger.info(
            "Crawler completed"
        )


if __name__ == "__main__":

    crawler = MSRITCrawler()

    crawler.run()