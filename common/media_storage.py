"""Cloudinary image storage tuned for low bandwidth and storage. Imported only when USE_CLOUDINARY is on."""

from pathlib import PurePosixPath

import cloudinary
import cloudinary.uploader
from cloudinary_storage.storage import MediaCloudinaryStorage

MAX_IMAGE_SIDE = 2000


class OptimizedCloudinaryStorage(MediaCloudinaryStorage):
    """
    Image storage on Cloudinary that keeps bandwidth and storage low.

    Uploads are shrunk on Cloudinary's side to at most MAX_IMAGE_SIDE pixels
    on the longer edge (never enlarged), so phone photos do not fill the
    quota. Links handed to browsers ask for f_auto,q_auto, so each browser
    gets the smallest format and quality it can show (WebP or AVIF).
    Reading a file on the server (for the AI service) still downloads the
    stored image in its original format.
    """

    def _upload(self, name, content):
        options = {
            "use_filename": True,
            "resource_type": self._get_resource_type(name),
            "tags": self.TAG,
            "transformation": [{"width": MAX_IMAGE_SIDE, "height": MAX_IMAGE_SIDE, "crop": "limit"}],
        }
        folder = str(PurePosixPath(name).parent)
        if folder != ".":
            options["folder"] = folder
        return cloudinary.uploader.upload(content, **options)

    def url(self, name):
        resource = cloudinary.CloudinaryResource(
            self._prepend_prefix(name),
            default_resource_type=self._get_resource_type(name),
        )
        return resource.build_url(fetch_format="auto", quality="auto", secure=True)
