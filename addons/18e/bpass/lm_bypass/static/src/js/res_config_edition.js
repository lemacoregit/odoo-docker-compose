import { patch } from "@web/core/utils/patch";
import { session } from "@web/session";
import { Setting } from "@web/views/form/setting/setting";

patch(Setting, {
    setup() {
        this.serverVersion = session.server_version;
        this.expirationDate = "This is an open version and has no expiration date."
    }
});