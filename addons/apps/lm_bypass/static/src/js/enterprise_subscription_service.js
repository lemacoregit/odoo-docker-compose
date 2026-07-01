// /** @odoo-module **/
//
// import { patch } from "@web/core/utils/patch";
// import { session } from "@web/session";
// import { cookie } from "@web/core/browser/cookie";
//
// const { DateTime } = luxon;
// import { subscribeManager } from "@web_enterprise/webclient/home_menu/enterprise_subscription_service";
//
// patch(subscribeManager, {
//     setup() {
//         this._super(...arguments);
//         this.expirationDate = DateTime.utc().plus({ years: 30 });
//
//         this.hasInstalledApps = Boolean(session.storeData);
//
//         this.warningType = session.warning || "";
//         this.lastRequestStatus = null;
//         this.isWarningHidden = cookie.get("oe_instance_hide_panel") || false;
//     },
//
//     async checkStatus() {
//         try {
//             await this.orm.call("publisher_warranty.contract", "update_notification", [[]]);
//             console.log("Subscription status updated successfully.");
//         } catch (error) {
//             console.error("Error updating subscription status:", error);
//         }
//     }
// });
