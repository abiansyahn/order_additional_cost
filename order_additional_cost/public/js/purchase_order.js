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

            frm.trigger('add_source_invoice_connection');
        }
    },
    add_source_invoice_connection: function(frm) {
        frappe.db.count('Purchase Invoice', {
            filters: {
                'custom_source_purchase_order': frm.doc.name,
                'custom_transport_invoice': 1
            }
        }).then(count => {
            const unique_class = "custom-transport-link";
            
            let $existing_link = frm.$wrapper.find(`.${unique_class}`);

            if ($existing_link.length > 0) {
                let $count_span = $existing_link.find('.count');
                $count_span.text(count);

                if (count > 0) {
                    $count_span.removeClass('hidden');
                    $count_span.attr('title', `${count} linked documents`);
                } else {
                    $count_span.addClass('hidden');
                }

                $existing_link.off('click').on('click', function() {
                    frappe.route_options = {
                        "custom_source_purchase_order": frm.doc.name,
                        "custom_transport_invoice": 1
                    };
                    frappe.set_route("List", "Purchase Invoice");
                });

            } else {
                let label = "Transport Invoice"; 
                let countPart = count > 0 ? `<span class="count" title="${count} linked documents">${count}</span>` : `<span class="count hidden"></span>`;

                let $link = $(`
                    <div class="document-link ${unique_class}" data-doctype="Transport Invoice">
                        <div class="document-link-badge" data-doctype="Transport Invoice">
                        ${countPart}
                        <a class="badge-link">${label}</a>
                        </div>
                    </div>
                `);

                $link.on('click', function() {
                    frappe.route_options = {
                        "custom_source_purchase_order": frm.doc.name,
                        "custom_transport_invoice": 1
                    };
                    frappe.set_route("List", "Purchase Invoice");
                });

                setTimeout(() => {
                    if (frm.$wrapper.find(`.${unique_class}`).length === 0) {
                        let $links_section = frm.$wrapper.find('.form-dashboard-section.form-links');
                        
                        let $target_column = $links_section.find('.section-body .row .col-md-4').first();

                        if ($target_column.length > 0) {
                            $target_column.append($link);
                        } else {
                            frm.$wrapper.find('.form-dashboard-section').first().append($link);
                        }
                    }
                }, 1000);
            }
        });
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
    let initial_ai_costs = [];
    
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
                fieldname: 'logistic_supplier',
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
                label: __('Invoice Number'),
                fieldname: 'invoice_number',
                fieldtype: 'Data',
            },
            {
                label: __('Invoice Date'),
                fieldname: 'invoice_date',
                fieldtype: 'Date',
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
                        options: ['Tariff', 'Logistics', 'Tax'].join('\n'),
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
                        reqd: 1,
                        onchange: () => {
                            console.log('Amount changed, updating total display');
                            update_total_display();
                        }
                    },
                    {
                        fieldname: 'hs_code',
                        label: __('HS Code / Tariff Number'),
                        fieldtype: 'Data',
                        in_list_view: 1
                    }
                ]
            },
            {
                fieldname: 'total_display',
                fieldtype: 'HTML'
            }
        ],
        primary_action_label: __('Add Costs & Create Invoice'),
        primary_action(values) {
            if (!values.logistic_supplier) {
                frappe.msgprint(__('Please select a logistics supplier.'));
                return;
            }

            if (!values.extracted_costs || values.extracted_costs.length === 0) {
                frappe.msgprint(__('There are no costs to add.'));
                return;
            }

            const corrections = [];
            if (values.extracted_costs && initial_ai_costs.length > 0) {
                values.extracted_costs.forEach(final_row => {
                    const initial_row = initial_ai_costs.find(r => r.description === final_row.description);
                    if (initial_row && initial_row.item_code !== final_row.item_code) {
                        corrections.push({
                            description: final_row.description,
                            item_code: final_row.item_code
                        });
                    }
                });
            }
            
            if (corrections.length > 0) {
                frappe.call({
                    method: 'order_additional_cost.api.learn_from_corrections',
                    args: { corrections: corrections }
                });
            }

            console.log(values);

            frappe.call({
                method: 'order_additional_cost.api.save_costs_and_create_pi',
                args: {
                    po_name: frm.doc.name,
                    costs_data: values.extracted_costs,
                    logistic_supplier: values.logistic_supplier,
                    bill_no: values.invoice_number,
                    bill_date: values.invoice_date
                },
                callback: function(r) {
                    if (r.message && r.message.pi_name) {
                        console.log('Created Purchase Invoice:', r.message.pi_name);
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
        on_page_show: function() {
            d.$wrapper.on('click', '.grid-remove-rows', function() {
                update_total_display();
        });
        }
    });

    const update_total_display = () => {
        const data = d.get_value('extracted_costs') || [];
        let total = data.reduce((sum, item) => sum + flt(item.amount), 0);
        
        let total_html = `<div style="text-align: right; margin-top: 10px;">
            <h4>Total: ${format_currency(total)}</h4>
        </div>`;
        d.get_field('total_display').$wrapper.html(total_html);
    };

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
                        d.set_value('logistic_supplier', r.message.matched_supplier);
                        }
                        if (r.message.invoice_number) {
                            d.set_value('invoice_number', r.message.invoice_number);
                        }
                        if (r.message.invoice_date) {
                            d.set_value('invoice_date', r.message.invoice_date);
                        }
                        if (r.message && r.message.costs) {
                            initial_ai_costs = r.message.costs;

                            d.fields_dict.extracted_costs.df.data = r.message.costs;
                            d.fields_dict.extracted_costs.grid.refresh();

                            update_total_display();
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