"""The website upload bundle must contain only public site files."""

from zipfile import ZipFile

from scripts.package_season3_website import package


def test_package_preserves_website_layout_and_excludes_admin_files(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "index.html").write_text('<a href="season3/">Season 3</a>')
    (home / "styles.css").write_text("body {}")
    gallery = tmp_path / "gallery"
    (gallery / "private" / "token").mkdir(parents=True)
    (gallery / "index.html").write_text("public")
    (gallery / "private" / "index.html").write_text("unavailable")
    (gallery / "private" / "token" / "index.html").write_text("personal")
    (tmp_path / "season3-delivery.csv").write_text("private admin data")
    output = tmp_path / "upload.zip"

    assert package(gallery, output, home=home) == 5
    with ZipFile(output) as archive:
        assert set(archive.namelist()) == {
            "index.html", "styles.css", "season3/index.html",
            "season3/private/index.html", "season3/private/token/index.html",
        }
