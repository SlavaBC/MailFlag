// Keep public destinations centralized here. Matching href values in HTML are fallbacks when JavaScript is unavailable.
const LINKS = {
  github: "https://github.com/SlavaBC/MailFlag",
  readme: "https://github.com/SlavaBC/MailFlag/blob/master/README.md",
  releases: "https://github.com/SlavaBC/MailFlag/releases/tag/v0.14.7-beta1",
  download: "https://github.com/SlavaBC/MailFlag/releases/download/v0.14.7-beta1/mailflag_0.14.7.beta1_amd64.deb",
  privacy: "https://github.com/SlavaBC/MailFlag/blob/master/PRIVACY.md",
  license: "https://github.com/SlavaBC/MailFlag/blob/master/LICENSE",
  issues: "https://github.com/SlavaBC/MailFlag/issues/new",
  featureRequest: "https://github.com/SlavaBC/MailFlag/issues/new",
  providerRequest: "https://github.com/SlavaBC/MailFlag/issues/new"
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
