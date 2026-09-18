# Graph IDs use the diagnostics path representation of numeric and string users.
# Infinity decodes JSON numbers through float64 before running jq.
def validate_graph_ids:
    if any((.users[].userId, .sources[].ownerUserId, .sources[].sourceId,
            .users[].subscriptions[].producerUserId, .users[].subscriptions[].sourceId);
           type == "number" and (. > 9007199254740991 or . < -9007199254740991))
    then error("Numeric diagnostics ID exceeds Infinity JSON integer precision") else . end;
def user_key: tostring;
def user_id($room; $user): "user:\($room):\($user | user_key)";
def source_id($room; $source): "source:\($room):\($source)";
def worker_id: "worker:\(.)";
def stream_label: if . == "" then "source" else . end;
def route_color: {active: "green", inactive: "gray", pending: "yellow"}[. // "unknown"] // "gray";
def health_color: {connected: "green", disconnected: "red"}[. // "unknown"] // "gray";
def observed: if . == null then "Not observed" else tostring end;
def user_node($room; $selected):
    (.userId | user_key) as $key |
    {
        id: user_id($room; .userId),
        title: ($key + if $key == $selected then " selected" else "" end),
        subTitle: (.transport.health // "unknown"),
        mainStat: "\(.transport.qualitySummary.currentIncomingBitrate.totalBps) bps",
        secondaryStat: "\(.publications | length) pub / \(.subscriptions | length) sub",
        color: (if $key == $selected then "blue" else (.transport.health | health_color) end),
        detail__connection: (.transport.connectionId | tostring),
        detail__worker: (.transport.mediaWorkerId | tostring)
    };
def missing_user_node($room):
    {id: user_id($room; .), title: (. | user_key), subTitle: "user not observed", color: "gray"};
def source_node($room; $downloads):
    {
        id: source_id($room; .sourceId),
        title: "\(.streamId | stream_label) #\(.sourceId)",
        subTitle: "\(if .active then "active" else "inactive" end) \(.mediaKind)",
        mainStat: "\(.currentIncomingBitrateBps) bps",
        secondaryStat: "\(.encodings | length) encodings / \($downloads) downloads",
        color: (if .active then "blue" else "gray" end),
        detail__owner_user: (.ownerUserId | user_key),
        detail__stream_id: (.streamId | stream_label),
        detail__transport_media_id: (.transportMediaId | observed),
        detail__mid: (.mid | observed),
        detail__encoding_ids: ([.encodings[].encodingId | tostring] | join(", ")),
        detail__rids: ([.encodings[].rid | select(. != null)] | join(", "))
    };
def missing_source_node($room):
    {id: source_id($room; .), title: "missing #\(.)", subTitle: "source not observed", color: "gray"};
def subscription_details:
    {
        mainStat: ((.streamId | stream_label) + if (.selection.selectedRid // "") == "" then "" else " " + .selection.selectedRid end),
        secondaryStat: .state,
        color: (.state | route_color),
        strokeDasharray: (if .state == "active" then "" else "5, 5" end),
        detail__source_id: (.sourceId | tostring),
        detail__producer_user: (.producerUserId | user_key),
        detail__selector: .selection.selector,
        detail__selection_reason: .selection.selectionReason,
        detail__selection_active: (.selection.active | tostring),
        detail__selected_encoding_id: (.selection.selectedEncodingId | observed),
        detail__selected_rid: (.selection.selectedRid | observed),
        detail__source_transport_media_id: (.sourceTransportMediaId | observed),
        detail__consumer_transport_media_id: (.consumerTransportMediaId | observed)
    };
def subscriptions: [.users[] as $user | $user.subscriptions[] | {receiver: $user, route: .}];
