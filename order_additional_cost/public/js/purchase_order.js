frappe.ui.form.on('Purchase Order', {
    refresh: function(frm) {
        if (!frm.is_new()) {
            frm.add_custom_button(__('Add Customs & Transport Costs'), function() {
                frappe.call({
                    method: 'order_additional_cost.api.check_settings',
                    callback: function(r) {
                        if (r.message && r.message.length > 0) {
                            let error_html = r.message.join('<br>');
                            frappe.msgprint({
                                title: __('Configuration Missing'),
                                indicator: 'red',
                                message: __('Please ask your system administrator to configure the following before proceeding:<br><br>' + error_html)
                            });
                        } else {
                            show_costs_dialog(frm);
                        }
                    }
                });
            });
        }
    }
});

frappe.ui.form.on('Purchase Order Shipping Cost', {
    custom_additional_shipping_cost_remove: function(frm, cdt, cdn) {
        let total = 0;
        frm.doc.custom_additional_shipping_cost.forEach(function(item) {
            total += item.amount;
        });
        frm.set_value('custom_total_shipping_cost_amount', total);
        frm.refresh_field('custom_total_shipping_cost_amount');
    }
})

function show_costs_dialog(frm) {
    let d = new frappe.ui.Dialog({
        title: __('Upload Logistics Invoice & Verify Costs'),
        fields: [
            {
                label: 'Logistics Invoice (PDF)',
                fieldname: 'invoice_pdf',
                fieldtype: 'Attach',
                reqd: 1,
                make_attachment_public: 1
            },
            {
                label: 'Logistics Supplier',
                fieldname: 'logistics_supplier',
                fieldtype: 'Link',
                options: 'Supplier',
                description: 'Supplier will be auto-matched. Please verify.',
                get_query: () => {
                    return {
                        filters: {
                            'supplier_group': 'Logistics'
                        }
                    };
                }
            },
            {
                fieldtype: 'Section Break',
                label: 'Verified Data'
            },
            {
                fieldname: 'extracted_costs',
                fieldtype: 'Table',
                label: __('Extracted Costs'),
                in_place_edit: true,
                fields: [
                    {
                        fieldname: 'category',
                        label: __('Category'),
                        fieldtype: 'Select',
                        options: ['Tariff', 'Logistics'].join('\n'),
                        in_list_view: 1,
                        reqd: 1
                    },
                    {
                        fieldname: 'item_code',
                        label: __('Item'),
                        fieldtype: 'Link',
                        options: 'Item',
                        in_list_view: 1,
                        reqd: 1,
                        get_query: () => {
                            return { filters: { 'is_stock_item': 0 } };
                        }
                    },
                    {
                        fieldname: 'item_description',
                        label: __('Item Description'),
                        fieldtype: 'Data',
                        in_list_view: 1,
                        reqd: 1
                    },
                    {
                        fieldname: 'description',
                        label: __('PDF Item Description'),
                        fieldtype: 'Data',
                        in_list_view: 1,
                        reqd: 1
                    },
                    {
                        fieldname: 'amount',
                        label: __('Amount'),
                        fieldtype: 'Currency',
                        in_list_view: 1,
                        reqd: 1
                    },
                    {
                        fieldname: 'hs_code',
                        label: __('HS Code / Tariff Number'),
                        fieldtype: 'Data',
                        in_list_view: 1
                    }
                ]
            }
        ],
        primary_action_label: __('Add Costs & Create Invoice'),
        primary_action(values) {
            if (!values.logistics_supplier) {
                frappe.msgprint(__('Please select a logistics supplier.'));
                return;
            }

            if (!values.extracted_costs || values.extracted_costs.length === 0) {
                frappe.msgprint(__('There are no costs to add.'));
                return;
            }

            frappe.call({
                method: 'order_additional_cost.api.save_costs_and_create_pi',
                args: {
                    po_name: frm.doc.name,
                    costs_data: values.extracted_costs,
                    logistic_supplier: values.logistic_supplier
                },
                callback: function(r) {
                    if (r.message && r.message.pi_name) {
                        frappe.show_alert({
                            message: __('Successfully added costs. Draft Purchase Invoice {0} created.', [r.message.pi_name]),
                            indicator: 'green'
                        });
                        frm.reload_doc();
                    }
                }
            });
            d.hide();
        },
    });

    $(d.parent).closest(".modal-dialog").css({width: '1200px', maxWidth: '100%'});

    d.fields_dict.invoice_pdf.df.onchange = () => {
        let file_url = d.get_values().invoice_pdf;
        if (file_url) {
            frappe.show_progress(__('Processing'), __('Reading & Matching Data...'));
            frappe.call({
                method: 'order_additional_cost.api.process_invoice_pdf',
                args: { file_url: file_url },
                callback: function(r) {
                    frappe.hide_progress();
                    if (r.message) {
                        if (r.message.matched_supplier) {
                        d.set_value('logistics_supplier', r.message.matched_supplier);
                        }
                        if (r.message && r.message.costs) {
                            d.fields_dict.extracted_costs.df.data = r.message.costs;
                            d.fields_dict.extracted_costs.grid.refresh();
                            frappe.show_alert({message: __('Please verify the extracted data below.'), indicator: 'blue'});
                        }
                        frappe.show_alert({message: __('Data has been extracted and matched. Please verify.'), indicator: 'blue'});
                    } else {
                        frappe.msgprint(__('Could not extract data from the PDF. Please enter manually into the table.'));
                    }
                },
                error: function(r) {
                    frappe.hide_progress();
                    frappe.msgprint(r.message || __('An error occurred during PDF processing.'));
                }
            });
        }
    };

    d.show();
}