// Replace public destinations here once they exist. Do not duplicate URLs in HTML.
const LINKS = {
  github: null,          // TODO: public GitHub repository URL
  readme: "README.md",
  releases: null,        // TODO: public GitHub Releases URL
  download: null,        // TODO: direct .deb URL
  privacy: "PRIVACY.md",
  license: null,         // TODO: public GPLv3 license URL
  issues: null,          // TODO: public issues URL
  featureRequest: null,  // TODO: public feature request URL
  providerRequest: null  // TODO: provider request URL
};

document.querySelectorAll("[data-link]").forEach((link) => {
  const url = LINKS[link.dataset.link];
  if (url) {
    link.href = url;
    link.removeAttribute("aria-disabled");
    if (/^https?:\/\//.test(url)) { link.target = "_blank"; link.rel = "noopener noreferrer"; }
  } else if (link.getAttribute("aria-disabled") === "true") {
    link.title = "Public URL is not available yet";
    link.addEventListener("click", (event) => event.preventDefault());
  }
});
