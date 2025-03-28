
jQuery(document).ready(function ($) {

    $('form.frm_ajax').submit(function (event) {

        var blocked_element = $(this).parent()
        // $(blocked_element).block();
        event.preventDefault()

        form = $(this)

        if ($("input, select, textarea").hasClass('is-invalid'))
            $("input, select, textarea").removeClass('is-invalid')

        if ($("input, select, textarea").next('p').length)
            $("input, select, textarea").nextAll('p').empty();

        let action = $(form).attr('action')
        let first_element = '';

        let form_id = $(form).attr("id")        
        var formData = new FormData(document.getElementById(form_id))

        $.post({
            url: action,
            data: formData,
            processData: false,
            contentType: false,
            error: function (xhr, status, error) {

                let errors = $.parseJSON(xhr.responseJSON.errors);

                for (var name in errors) {
                    for (var i in errors[name]) {
                        var $input = $("[name='" + name + "']");
                        $input.addClass('is-invalid');

                        $input.after("<p class='invalid-feedback'><strong class=''>" + errors[name][i].message + "</strong></p>");
                    }

                    if (first_element == '')
                        $input.focus()
                    else {
                        first_element = '-'
                    }
                }

                var span = document.createElement('span')
                span.innerHTML = xhr.responseJSON.message
                swal({
                    title: "Please review and try again",
                    content: span,
                    icon: 'warning'
                });

                $(blocked_element).unblock();
            },
            success: function (response) {
                swal({
                    title: 'Success',
                    text: response.message,
                    icon: response.status
                }).then(
                    (value) => {
                        inputsChanged = false
                        if (response.action == 'redirect_to')
                            location.href = response.redirect_to

                        if (response.action == 'reload')
                            location.reload();
                    }
                )
                $(blocked_element).unblock();
            }
        })
        return false
    });

});

$(document).ready(function() {
    $("#id_event").change(function() {
        var eventId = $(this).val();
        if (eventId) {
            $("#event_details").removeClass('d-none')
            $.ajax({
                url: record_event_info,
                data: { event_id: eventId },
                dataType: "json",
                success: function(data) {
                    $("#event_info").text(data.total_attended);
                    let col = ''
                    $( data.highschools ).each(function( index ) {
                        col += data.highschools[index] + "<br>"
                    });

                    $("#highschool_info").html(col);
                },
                error: function() {
                    $("#event_info").text("-");                                
                }
            });
        } else {
            $("#event_details").addClass('d-none')
        }
    });
});


setInterval(function() {

    if(!table.rows('.selected').any())
        table.ajax.reload(null, false);
}, 10000 * 60);

function do_bulk_action(action, dt) {

    if(!dt.rows('.selected').any()) {
        alert("Please select a row and try again.")
        return
    }

    var selectedRows = dt.rows({ selected: true });
    let data = {
        'action': action,
        'ids': Array()
    }
    selectedRows.every(function() {
        data.ids.push(this.id())
    })

    $(dt).block()

    url = record_bulk_action;
    let modal = "modal-bulk_actions"

    $.ajax({
        type: "GET",
        url: url,
        data: data,
        success: function(response) {
            $("#bulk_modal_content").html(response);
            $("#" + modal).modal('show');
        }
    });
}


$(document).ready(function () {


    $(document).on("click", "form.filter #id_btn_filter", function () {
        load_data();
    })

    function load_data() {
        let form = $('form.filter')
        let newURL = baseURL + '&' + $(form).serialize();

        table.ajax.url(newURL).load()
    }

    table = $('#records_all')
        .DataTable({
            initComplete: function () {
                this.api()
                    .columns()
                    .every(function () {
                        let column = this;
                        let title = column.footer().textContent;
        
                        // Create input element
                        if(title != '') {
                            let input = document.createElement('input');
                            input.className = 'form-control'
                            input.placeholder = "Search " + title;

                            column.footer().replaceChildren(input);
            
                            // Event listener for user input
                            input
                            .addEventListener('keyup', $.debounce(1500,() => {
                                if (column.search() !== this.value) {
                                    column.search(input.value).draw();
                                }
                            }));
                        }
                    });


                // Restore state
                var state = this.api().state.loaded();
                if (state) {
                    this.api().columns().eq(0).each(function (colIdx) {
                        var colSearch = state.columns[colIdx].search;
                        console.log(colSearch)

                        if (colSearch.search) {
                            $('input', this.column(colIdx).footer()).val(colSearch.search);
                        }
                    });
                }
            },
            searchDelay: 1500,
            columnDefs: [
                {
                    orderable: false,
                    className: 'select-checkbox',
                    targets: 0
                }
            ],
            select: {
                style: 'os',
                selector: 'td:first-child'
            },
            rowId: 'id',
            dom: 'B<"float-left mt-3 mb-3"l><"float-right mt-3"f><"row clear">rt<"row"<"col-6"i><"col-6 float-right"p>>',
            buttons: [
                {
                    extend: 'csv', className: 'btn btn-sm btn-primary text-white text-light',
                    text: '<i class="fas fa-file-csv text-white"></i>&nbsp;CSV',
                    titleAttr: 'Export Records in current View to CSV' 
                },
                { 
                    extend: 'print', className: 'btn btn-sm btn-primary text-white text-light',
                    text: '<i class="fas fa-print text-white"></i>&nbsp;Print',
                    titleAttr: 'Print Records in Current View' 
                },
                {
                    className: 'btn btn-sm btn-primary text-white text-light',
                    text: '<i class="fas fa-edit text-white"></i>&nbsp;Update Status',
                    titleAttr: 'Update Status',
                    action: function ( e, dt, node, config ) {
                        do_bulk_action('update_status', dt)
                    }
                },
            ],
            'orderCellsTop': true,
            'fixedHeader': true,
            // searching: false,
            ajax: '{{api_url}}',
            serverSide: true,
            processing: true,
            order: [[1, 'desc']],
            // stateSave: true,
            language: {
                'loadingRecords': '&nbsp;',
            },
            'lengthMenu': [30, 50, 100],

            'columns': [
                {
                    'searchable': false,
                    'orderable': false,
                    'render': function (data, type, row, meta) {
                        return ''
                    }
                },
                null,
                null,
                null,
                {
                    'render': function (data, type, row, meta) {
                            return row.highschool.name + "<br>" + row.billing_contact
                    },
                },
                null,
                null,
                {
                    'searchable': false,
                    'orderable': false,
                    'render': function (data, type, row, meta) {
                        return "<a class='btn btn-sm btn-primary record-details' refresh-target='table' href='" + row.ce_url + "'>View Details</a>"
                    }
                }
            ]
        }
    );
});