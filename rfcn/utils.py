import collections

import cv2
import dlib
import fcn
import numpy as np
import PIL.Image
import skimage.color


def label2instance_boxes(label_instance, label_class,
                         ignore_instance=-1, ignore_class=(-1, 0),
                         return_masks=False):
    """Convert instance label to boxes.

    Parameters
    ----------
    label_instance: numpy.ndarray, (H, W)
        Label image for instance id.
    label_class: numpy.ndarray, (H, W)
        Label image for class.
    ignore_instance: int or tuple of int
        Label value ignored about label_instance. (default: -1)
    ignore_class: int or tuple of int
        Label value ignored about label_class. (default: (-1, 0))
    return_masks: bool
        Flag to return each instance mask.

    Returns
    -------
    instance_classes: numpy.ndarray, (n_instance,)
        Class id for each instance.
    boxes: (n_instance, 4)
        Bounding boxes for each instance. (x1, y1, x2, y2)
    instance_masks: numpy.ndarray, (n_instance, H, W), bool
        Masks for each instance. Only returns when return_masks=True.
    """
    if not isinstance(ignore_instance, collections.Iterable):
        ignore_instance = (ignore_instance,)
    if not isinstance(ignore_class, collections.Iterable):
        ignore_class = (ignore_class,)
    # instance_class is 'Class of the Instance'
    instance_classes = []
    boxes = []
    instance_masks = []
    instances = np.unique(label_instance)
    for inst in instances:
        if inst in ignore_instance:
            continue

        mask_inst = label_instance == inst
        count = collections.Counter(label_class[mask_inst].tolist())
        instance_class = max(count.items(), key=lambda x: x[1])[0]

        if instance_class in ignore_class:
            continue

        where = np.argwhere(mask_inst)
        (y1, x1), (y2, x2) = where.min(0), where.max(0) + 1

        instance_classes.append(instance_class)
        boxes.append((x1, y1, x2, y2))
        instance_masks.append(mask_inst)
    instance_classes = np.array(instance_classes)
    boxes = np.array(boxes)
    instance_masks = np.array(instance_masks)
    if return_masks:
        return instance_classes, boxes, instance_masks
    else:
        return instance_classes, boxes


def draw_instance_boxes(img, boxes, instance_classes, n_class,
                        captions=None, bg_class=0):
    """Draw labeled rectangles on image.

    Parameters
    ----------
    img: numpy.ndarray
        RGB image.
    boxes: list of tuple
        Bounding boxes (x1, y1, x2, y2).

    Returns
    -------
    img_viz: numpy.ndarray
        RGB image.
    """
    n_boxes = len(boxes)
    assert n_boxes == len(instance_classes)
    if captions is not None:
        assert n_boxes == len(captions)

    img_viz = img.copy()
    cmap = fcn.utils.labelcolormap(n_class)

    CV_AA = 16
    for i_box in xrange(n_boxes):
        box = boxes[i_box]
        inst_class = instance_classes[i_box]

        if inst_class == bg_class:
            continue

        # get color for the label
        color = cmap[inst_class]
        color = (color * 255).tolist()

        x1, y1, x2, y2 = box
        cv2.rectangle(img_viz, (x1, y1), (x2, y2), color[::-1], 0, CV_AA)

        if captions is not None:
            caption = captions[i_box]
            font_scale = 0.4
            ret, baseline = cv2.getTextSize(
                caption, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
            cv2.rectangle(img_viz, (x1, y2 - ret[1] - baseline),
                          (x1 + ret[0], y2), color[::-1], -1)
            cv2.putText(img_viz, caption, (x1, y2 - baseline),
                        cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255),
                        1, CV_AA)

    return img_viz


def mask_to_bbox(mask):
    """Convert mask image to bounding box.

    Parameters
    ----------
    mask: :class:`numpy.ndarray`
        Input mask image.

    Returns
    -------
    box: tuple (x1, y1, x2, y2)
        Bounding box.
    """
    where = np.argwhere(mask)
    (y1, x1), (y2, x2) = where.min(0), where.max(0) + 1
    bbox = x1, y1, x2, y2
    return bbox


def label_to_bboxes(label, ignore_label=-1):
    """Convert label image to bounding boxes."""
    if not isinstance(ignore_label, collections.Iterable):
        ignore_label = (ignore_label,)
    bboxes = []
    for l in np.unique(label):
        if l in ignore_label:
            continue
        mask = label == l
        bbox = mask_to_bbox(mask)
        bboxes.append(bbox)
    return np.array(bboxes)


def resize_image(img, shape):
    height, width = shape[:2]
    img_pil = PIL.Image.fromarray(img)
    img_pil = img_pil.resize((width, height))
    return np.array(img_pil)


def get_bbox_overlap(bbox1, bbox2):
    x11, y11, x12, y12 = bbox1
    x21, y21, x22, y22 = bbox2
    w1, h1 = x12 - x11, y12 - y11
    w2, h2 = x22 - x21, y22 - y21
    intersect = (max(0, min(x12, x22) - max(x11, x21)) *
                 max(0, min(y12, y22) - max(y11, y21)))
    union = w1 * h1 + w2 * h2 - intersect
    return 1.0 * intersect / union


def label_rois(rois, label_instance, label_class, overlap_thresh=0.5):
    """Label rois for instance classes.

    Parameters
    ----------
    rois: numpy.ndarray, (n_rois, 4)
    label_instance: numpy.ndarray, (H, W)
    label_class: numpy.ndarray, (H, W)
    overlap_thresh: float, [0, 1]
        Threshold to label as fg. (default: 0.5)

    Returns
    -------
    roi_clss: numpy.ndarray, (n_rois,), numpy.int32
    roi_inst_masks: list of numpy.ndarray
    """
    inst_clss, inst_rois, inst_masks = label2instance_boxes(
        label_instance, label_class, return_masks=True)
    roi_clss = []
    roi_inst_masks = []
    for roi in rois:
        overlaps = [get_bbox_overlap(roi, inst_roi) for inst_roi in inst_rois]
        inst_ind = np.argmax(overlaps)
        overlap = overlaps[inst_ind]

        if overlap > overlap_thresh:
            roi_cls = inst_clss[inst_ind]
            x1, y1, x2, y2 = roi
            roi_inst_mask = inst_masks[inst_ind][y1:y2, x1:x2]
        else:
            roi_cls = 0
            roi_inst_mask = None
        roi_clss.append(roi_cls)
        roi_inst_masks.append(roi_inst_mask)
    roi_clss = np.array(roi_clss, dtype=np.int32)
    return roi_clss, roi_inst_masks


def get_mask_overlap(mask1, mask2):
    intersect = np.bitwise_and(mask1, mask2).sum()
    union = np.bitwise_or(mask1, mask2).sum()
    return 1.0 * intersect / union


def instance_label_accuracy_score(lbl_ins1, lbl_ins2):
    best_overlaps = []
    for l1 in np.unique(lbl_ins1):
        if l1 == -1:
            continue
        mask1 = lbl_ins1 == l1
        best_overlap = 0
        for l2 in np.unique(lbl_ins2):
            if l2 == -1:
                continue
            mask2 = lbl_ins2 == l2
            overlap = get_mask_overlap(mask1, mask2)
            best_overlap = max(best_overlap, overlap)
        best_overlaps.append(best_overlap)
    return np.mean(best_overlaps)


def get_region_proposals(img, kvals=(50, 200, 3), min_size=20,
                         max_merging_iterations=50):
    rects = []
    dlib.find_candidate_object_locations(
        img, rects, kvals, min_size, max_merging_iterations)
    rois = []
    for r in rects:
        x1, y1, x2, y2 = r.left(), r.top(), r.right(), r.bottom()
        roi_h, roi_w = y2 - y1, x2 - x1
        if roi_h * roi_w > 0:
            rois.append((x1, y1, x2, y2))
    rois = np.array(rois, dtype=np.int32)
    return rois


def get_positive_negative_samples(is_positive, negative_ratio=1.0):
    assert isinstance(is_positive, np.ndarray)
    assert is_positive.dtype == bool
    n_positive = is_positive.sum()
    n_negative = int(negative_ratio * n_positive)
    # get samples for specified negative ratio
    samples = np.where(is_positive)[0]
    is_negative = ~is_positive
    negative_samples = np.random.choice(np.where(is_negative)[0], n_negative)
    samples = np.hstack((samples, negative_samples))
    return samples


def visualize_instance_segmentation(lbl_ins, lbl_cls, img, class_names):
    # visualize instances
    lbl_ins = lbl_ins.copy()
    lbl_ins[lbl_cls == 0] = -1
    viz = skimage.color.label2rgb(lbl_ins, img, bg_label=-1)
    viz = (viz * 255).astype(np.uint8)
    # visualize classes
    ins_clss, boxes = label2instance_boxes(
        lbl_ins, lbl_cls, ignore_class=(-1, 0))
    if ins_clss.size > 0:
        viz = draw_instance_boxes(
            viz, boxes, ins_clss,
            n_class=len(class_names),
            captions=class_names[ins_clss])
    return viz
