# This file includes adapted code from MMPose (OpenMMLab).
# This implementation improves the funcitonality by returning 
# a 2d pose visualiztion on the input image as well as a list of 3D pose visualizations.
# Modifications and enhancements by: Navid Salami Pargoo.

import math
from typing import Dict, List, Optional, Tuple, Union

import cv2
import mmcv
import numpy as np
import matplotlib
matplotlib.use('Agg') 
from matplotlib import pyplot as plt
plt.ioff()
from mmengine.dist import master_only
from mmengine.structures import InstanceData

from mmpose.apis import convert_keypoint_definition
from mmpose.registry import VISUALIZERS
from mmpose.structures import PoseDataSample
from . import PoseLocalVisualizer

import colorsys

@VISUALIZERS.register_module()
class Pose3dLocalVisualizer(PoseLocalVisualizer):
    """3d Local Visualizer.

    Args:
        name (str): Name of the instance. Defaults to 'visualizer'.
        image (np.ndarray, optional): the origin image to draw. The format
            should be RGB. Defaults to ``None``
        vis_backends (list, optional): Visual backend config list. Defaults to
            ``None``
        save_dir (str, optional): Save file dir for all storage backends.
            If it is ``None``, the backend storage will not save any data.
            Defaults to ``None``
        bbox_color (str, tuple(int), optional): Color of bbox lines.
            The tuple of color should be in BGR order. Defaults to ``'green'``
        kpt_color (str, tuple(tuple(int)), optional): Color of keypoints.
            The tuple of color should be in BGR order. Defaults to ``'red'``
        link_color (str, tuple(tuple(int)), optional): Color of skeleton.
            The tuple of color should be in BGR order. Defaults to ``None``
        line_width (int, float): The width of lines. Defaults to 1
        radius (int, float): The radius of keypoints. Defaults to 4
        show_keypoint_weight (bool): Whether to adjust the transparency
            of keypoints according to their score. Defaults to ``False``
        alpha (int, float): The transparency of bboxes. Defaults to ``0.8``
        det_kpt_color (str, tuple(tuple(int)), optional): Keypoints color
             info for detection. Defaults to ``None``
        det_dataset_skeleton (list): Skeleton info for detection. Defaults to
            ``None``
        det_dataset_link_color (list): Link color for detection. Defaults to
            ``None``
    """

    def __init__(
            self,
            name: str = 'visualizer',
            image: Optional[np.ndarray] = None,
            vis_backends: Optional[Dict] = None,
            save_dir: Optional[str] = None,
            bbox_color: Optional[Union[str, Tuple[int]]] = 'green',
            kpt_color: Optional[Union[str, Tuple[Tuple[int]]]] = 'red',
            link_color: Optional[Union[str, Tuple[Tuple[int]]]] = None,
            text_color: Optional[Union[str, Tuple[int]]] = (255, 255, 255),
            skeleton: Optional[Union[List, Tuple]] = None,
            line_width: Union[int, float] = 1,
            radius: Union[int, float] = 3,
            show_keypoint_weight: bool = False,
            backend: str = 'opencv',
            alpha: float = 0.8,
            det_kpt_color: Optional[Union[str, Tuple[Tuple[int]]]] = None,
            det_dataset_skeleton: Optional[Union[str,
                                                 Tuple[Tuple[int]]]] = None,
            det_dataset_link_color: Optional[np.ndarray] = None):
        super().__init__(name, image, vis_backends, save_dir, bbox_color,
                         kpt_color, link_color, text_color, skeleton,
                         line_width, radius, show_keypoint_weight, backend,
                         alpha)
        self.det_kpt_color = det_kpt_color
        self.det_dataset_skeleton = det_dataset_skeleton
        self.det_dataset_link_color = det_dataset_link_color

    def _draw_3d_data_samples(self,
                              pose_samples: PoseDataSample,
                              track_ids: List[int] = [],
                              kpt_thr: float = 0.3,
                              num_instances=5,
                              plot_size: int = 300,
                              axis_azimuth: float = 70,
                              axis_limit: float = 1.7,
                              axis_dist: float = 10.0,
                              axis_elev: float = 15.0,
                              show_kpt_idx: bool = False,
                              scores_2d: Optional[np.ndarray] = None):
        """Draw keypoints and skeletons (optional) of GT or prediction.

        Args:
            instances (:obj:`InstanceData`): Data structure for
                instance-level annotations or predictions.
            kpt_thr (float, optional): Minimum threshold of keypoints
                to be shown. Default: 0.3.
            num_instances (int): Number of instances to be shown in 3D. If
                smaller than 0, all the instances in the pose_result will be
                shown. Otherwise, pad or truncate the pose_result to a length
                of num_instances.
            plot_size (int): The size of the plot. Defaults to 300.
            axis_azimuth (float): axis azimuth angle for 3D visualizations.
            axis_dist (float): axis distance for 3D visualizations.
            axis_elev (float): axis elevation view angle for 3D visualizations.
            axis_limit (float): The axis limit to visualize 3d pose. The xyz
                range will be set as:
                - x: [x_c - axis_limit/2, x_c + axis_limit/2]
                - y: [y_c - axis_limit/2, y_c + axis_limit/2]
                - z: [0, axis_limit]
                Where x_c, y_c is the mean value of x and y coordinates
            show_kpt_idx (bool): Whether to show the index of keypoints.
                Defaults to ``False``
            scores_2d (np.ndarray, optional): Keypoint scores of 2d estimation
                that will be used to filter 3d instances.

        Returns:
            List[np.ndarray]: the list of drawn 3d pose estimations.
        """
        pose3d_data_dic = {}  # Dictionary to store individual subplots
        need_dummy_plot = False # if len(pred_instances) is less than num_instances

        if 'pred_instances' in pose_samples:
            pred_instances = pose_samples.pred_instances
        else:
            pred_instances = InstanceData()

        if num_instances < 0:
            if 'keypoints' in pred_instances:
                num_instances = len(pred_instances)
            else:
                num_instances = 0
        else:
            if len(pred_instances) > num_instances:
                pred_instances_ = InstanceData()
                for k in pred_instances.keys():
                    new_val = pred_instances[k][:num_instances]
                    pred_instances_.set_field(new_val, k)
                pred_instances = pred_instances_
            else:
                need_dummy_plot = True

        def _draw_3d_instances_kpts(keypoints,
                                    scores,
                                    scores_2d,
                                    keypoints_visible,
                                    track_ids,
                                    fig_idx,
                                    show_kpt_idx,
                                    title=None):

            def get_color(idx):
                golden_ratio_conjugate = 0.618033988749895
                h = (idx * golden_ratio_conjugate) % 1.0
                s = 0.4 + (idx % 5) * 0.1
                l = 0.4 + (idx % 3) * 0.1
                r, g, b = colorsys.hls_to_rgb(h, l, s)
                return [r, g, b]

            for idx, (kpts, score, score_2d) in enumerate(zip(keypoints, scores, scores_2d)):
                skip = False
                if track_ids[idx] == -1:
                    continue
                # valid = np.logical_and(score >= kpt_thr, score_2d >= kpt_thr,
                #                        np.any(~np.isnan(kpts), axis=-1))
                # kpts_valid = kpts[valid]
                kpts_valid = kpts

                if np.mean(score) < kpt_thr or np.mean(score_2d) < kpt_thr:
                    skip = True

                # Create a new figure for each instance
                fig = plt.figure(
                    figsize=(plot_size/100, plot_size/100), 
                    dpi=100
                    )
                ax = fig.add_subplot(111, projection='3d')
                ax.view_init(elev=axis_elev, azim=axis_azimuth)
                ax.set_aspect('auto')
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_zticks([])
                ax.set_xticklabels([])
                ax.set_yticklabels([])
                ax.set_zticklabels([])

                if title:
                    ax.set_title(f'{title} ({track_ids[idx]})', color='white', backgroundcolor=get_color(track_ids[idx]))
                    ax.title.set_fontweight('bold')
                    ax.title.set_fontsize(20)
                ax.dist = axis_dist

                if skip:
                    fig.tight_layout()
                    fig.canvas.draw()
                else:                    
                    # x_c = np.mean(kpts_valid[:, 0]) if valid.any() else 0
                    # y_c = np.mean(kpts_valid[:, 1]) if valid.any() else 0
                    # z_c = np.mean(kpts_valid[:, 2]) if valid.any() else 0
                    x_c = np.mean(kpts_valid[:, 0])
                    y_c = np.mean(kpts_valid[:, 1])
                    z_c = np.mean(kpts_valid[:, 2])

                    ax.set_xlim3d([x_c - axis_limit / 2, x_c + axis_limit / 2])
                    ax.set_ylim3d([y_c - axis_limit / 2, y_c + axis_limit / 2])
                    ax.set_zlim3d([min(0, z_c - axis_limit / 2), z_c + axis_limit / 2])

                    if self.kpt_color is None or isinstance(self.kpt_color, str):
                        kpt_color = [self.kpt_color] * len(kpts)
                    elif len(self.kpt_color) == len(kpts):
                        kpt_color = self.kpt_color
                    else:
                        raise ValueError(f'the length of kpt_color ({len(self.kpt_color)}) does not matches that of keypoints ({len(kpts)})')

                    x_3d, y_3d, z_3d = np.split(kpts_valid[:, :3], [1, 2], axis=1)
                    # kpt_color = kpt_color[valid] / 255.
                    kpt_color = kpt_color / 255.
                    ax.scatter(x_3d, y_3d, z_3d, marker='o', c=kpt_color)

                    if show_kpt_idx:
                        for kpt_idx in range(len(x_3d)):
                            ax.text(x_3d[kpt_idx][0], y_3d[kpt_idx][0],
                                    z_3d[kpt_idx][0], str(kpt_idx))

                    if self.skeleton is not None and self.link_color is not None:
                        if self.link_color is None or isinstance(self.link_color, str):
                            link_color = [self.link_color] * len(self.skeleton)
                        elif len(self.link_color) == len(self.skeleton):
                            link_color = self.link_color
                        else:
                            raise ValueError(f'the length of link_color ({len(self.link_color)}) does not matches that of skeleton ({len(self.skeleton)})')

                        for sk_id, sk in enumerate(self.skeleton):
                            sk_indices = [_i for _i in sk]
                            xs_3d = kpts[sk_indices, 0]
                            ys_3d = kpts[sk_indices, 1]
                            zs_3d = kpts[sk_indices, 2]
                            kpt_score = score[sk_indices]
                            kpt_score_2d = score_2d[sk_indices]
                            if kpt_score.min() > kpt_thr and kpt_score_2d.min() > kpt_thr:
                                _color = link_color[sk_id] / 255.
                                ax.plot(xs_3d, ys_3d, zs_3d, color=_color, zdir='z')

                    fig.tight_layout()
                    fig.canvas.draw()

                # Convert the figure to a numpy array
                pred_img_data = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
                if not pred_img_data.any():
                    pred_img_data = np.full((plot_size, plot_size, 3), 255)
                else:
                    pred_img_data = pred_img_data.reshape(plot_size, plot_size, 3)

                plt.close(fig)

                # append to the pose3d_data_dic
                pose3d_data_dic[track_ids[idx]] = pred_img_data

        if 'keypoints' in pred_instances:
            keypoints = pred_instances.get('keypoints', pred_instances.keypoints)
            if 'keypoint_scores' in pred_instances:
                scores = pred_instances.keypoint_scores
            else:
                scores = np.ones(keypoints.shape[:-1])

            if scores_2d is None:
                scores_2d = np.ones(keypoints.shape[:-1])

            if 'keypoints_visible' in pred_instances:
                keypoints_visible = pred_instances.keypoints_visible
            else:
                keypoints_visible = np.ones(keypoints.shape[:-1])

            _draw_3d_instances_kpts(keypoints, scores, scores_2d,
                                    keypoints_visible, track_ids, 1, show_kpt_idx,
                                    'Track id')

        if need_dummy_plot:  
            num_dummy_plots = num_instances - len(pose3d_data_dic)
            for i in range(num_dummy_plots):
                fig = plt.figure(figsize=(plot_size/100, plot_size/100), dpi=100)
                ax = fig.add_subplot(111, projection='3d')
                ax.view_init(elev=axis_elev, azim=axis_azimuth)
                ax.set_aspect('auto')
                ax.set_xticks([])
                ax.set_yticks([])
                ax.set_zticks([])
                ax.set_xticklabels([])
                ax.set_yticklabels([])
                ax.set_zticklabels([])
                ax.set_title('NO DATA', color='white')
                ax.title.set_fontsize(20)
                fig.tight_layout()
                fig.canvas.draw()
                pred_img_data = np.frombuffer(fig.canvas.tostring_rgb(), dtype=np.uint8)
                if not pred_img_data.any():
                    pred_img_data = np.full((plot_size, plot_size, 3), 255)
                else:
                    pred_img_data = pred_img_data.reshape(plot_size, plot_size, 3)
                plt.close(fig)
                pose3d_data_dic[-1 * (i + 2)] = pred_img_data

        return pose3d_data_dic 

    def _draw_instances_kpts(self,
                             image: np.ndarray,
                             instances: InstanceData,
                             kpt_thr: float = 0.3,
                             show_kpt_idx: bool = False,
                             skeleton_style: str = 'mmpose',
                             track_ids: Optional[List[int]] = []):
        """Draw keypoints and skeletons (optional) of GT or prediction.

        Args:
            image (np.ndarray): The image to draw.
            instances (:obj:`InstanceData`): Data structure for
                instance-level annotations or predictions.
            kpt_thr (float, optional): Minimum threshold of keypoints
                to be shown. Default: 0.3.
            show_kpt_idx (bool): Whether to show the index of keypoints.
                Defaults to ``False``
            skeleton_style (str): Skeleton style selection. Defaults to
                ``'mmpose'``

        Returns:
            np.ndarray: the drawn image which channel is RGB.
        """

        self.set_image(image)
        img_h, img_w, _ = image.shape
        scores = None

        if 'keypoints' in instances:
            keypoints = instances.get('transformed_keypoints',
                                      instances.keypoints)

            if 'keypoint_scores' in instances:
                scores = instances.keypoint_scores
            else:
                scores = np.ones(keypoints.shape[:-1])

            if 'keypoints_visible' in instances:
                keypoints_visible = instances.keypoints_visible
            else:
                keypoints_visible = np.ones(keypoints.shape[:-1])

            if skeleton_style == 'openpose':
                keypoints_info = np.concatenate(
                    (keypoints, scores[..., None], keypoints_visible[...,
                                                                     None]),
                    axis=-1)
                # compute neck joint
                neck = np.mean(keypoints_info[:, [5, 6]], axis=1)
                # neck score when visualizing pred
                neck[:, 2:4] = np.logical_and(
                    keypoints_info[:, 5, 2:4] > kpt_thr,
                    keypoints_info[:, 6, 2:4] > kpt_thr).astype(int)
                new_keypoints_info = np.insert(
                    keypoints_info, 17, neck, axis=1)

                mmpose_idx = [
                    17, 6, 8, 10, 7, 9, 12, 14, 16, 13, 15, 2, 1, 4, 3
                ]
                openpose_idx = [
                    1, 2, 3, 4, 6, 7, 8, 9, 10, 12, 13, 14, 15, 16, 17
                ]
                new_keypoints_info[:, openpose_idx] = \
                    new_keypoints_info[:, mmpose_idx]
                keypoints_info = new_keypoints_info

                keypoints, scores, keypoints_visible = keypoints_info[
                    ..., :2], keypoints_info[..., 2], keypoints_info[..., 3]

            kpt_color = self.kpt_color
            if self.det_kpt_color is not None:
                kpt_color = self.det_kpt_color

            for idx, (kpts, score, visible) in enumerate(zip(keypoints, scores,
                                            keypoints_visible)):
                if track_ids[idx] == -1:
                    continue

                kpts = np.array(kpts[..., :2], copy=False)

                if kpt_color is None or isinstance(kpt_color, str):
                    kpt_color = [kpt_color] * len(kpts)
                elif len(kpt_color) == len(kpts):
                    kpt_color = kpt_color
                else:
                    raise ValueError(f'the length of kpt_color '
                                     f'({len(kpt_color)}) does not matches '
                                     f'that of keypoints ({len(kpts)})')

                # draw each point on image
                for kid, kpt in enumerate(kpts):
                    if score[kid] < kpt_thr or not visible[
                            kid] or kpt_color[kid] is None:
                        # skip the point that should not be drawn
                        continue

                    color = kpt_color[kid]
                    if not isinstance(color, str):
                        color = tuple(int(c) for c in color)
                    transparency = self.alpha
                    if self.show_keypoint_weight:
                        transparency *= max(0, min(1, score[kid]))
                    self.draw_circles(
                        kpt,
                        radius=np.array([self.radius]),
                        face_colors=color,
                        edge_colors=color,
                        alpha=transparency,
                        line_widths=self.radius)
                    if show_kpt_idx:
                        self.draw_texts(
                            str(kid),
                            kpt,
                            colors=color,
                            font_sizes=self.radius * 3,
                            vertical_alignments='bottom',
                            horizontal_alignments='center')

                # draw links
                skeleton = self.skeleton
                if self.det_dataset_skeleton is not None:
                    skeleton = self.det_dataset_skeleton
                link_color = self.link_color
                if self.det_dataset_link_color is not None:
                    link_color = self.det_dataset_link_color
                if skeleton is not None and link_color is not None:
                    if link_color is None or isinstance(link_color, str):
                        link_color = [link_color] * len(skeleton)
                    elif len(link_color) == len(skeleton):
                        link_color = link_color
                    else:
                        raise ValueError(
                            f'the length of link_color '
                            f'({len(link_color)}) does not matches '
                            f'that of skeleton ({len(skeleton)})')

                    for sk_id, sk in enumerate(skeleton):
                        pos1 = (int(kpts[sk[0], 0]), int(kpts[sk[0], 1]))
                        pos2 = (int(kpts[sk[1], 0]), int(kpts[sk[1], 1]))
                        if not (visible[sk[0]] and visible[sk[1]]):
                            continue

                        if (pos1[0] <= 0 or pos1[0] >= img_w or pos1[1] <= 0
                                or pos1[1] >= img_h or pos2[0] <= 0
                                or pos2[0] >= img_w or pos2[1] <= 0
                                or pos2[1] >= img_h or score[sk[0]] < kpt_thr
                                or score[sk[1]] < kpt_thr
                                or link_color[sk_id] is None):
                            # skip the link that should not be drawn
                            continue
                        X = np.array((pos1[0], pos2[0]))
                        Y = np.array((pos1[1], pos2[1]))
                        color = link_color[sk_id]
                        if not isinstance(color, str):
                            color = tuple(int(c) for c in color)
                        transparency = self.alpha
                        if self.show_keypoint_weight:
                            transparency *= max(
                                0, min(1, 0.5 * (score[sk[0]] + score[sk[1]])))

                        if skeleton_style == 'openpose':
                            mX = np.mean(X)
                            mY = np.mean(Y)
                            length = ((Y[0] - Y[1])**2 + (X[0] - X[1])**2)**0.5
                            angle = math.degrees(
                                math.atan2(Y[0] - Y[1], X[0] - X[1]))
                            stickwidth = 2
                            polygons = cv2.ellipse2Poly(
                                (int(mX), int(mY)),
                                (int(length / 2), int(stickwidth)), int(angle),
                                0, 360, 1)

                            self.draw_polygons(
                                polygons,
                                edge_colors=color,
                                face_colors=color,
                                alpha=transparency)

                        else:
                            self.draw_lines(
                                X, Y, color, line_widths=self.line_width)

        return self.get_image(), scores

    @master_only
    def add_datasample(self,
                       image: np.ndarray,
                       data_sample: PoseDataSample,
                       det_data_sample: Optional[PoseDataSample] = [],
                       track_ids: Optional[List[int]] = None,
                       draw_2d: bool = True,
                       draw_bbox: bool = False,
                       show_kpt_idx: bool = False,
                       skeleton_style: str = 'mmpose',
                       dataset_2d: str = 'coco',
                       dataset_3d: str = 'h36m',
                       convert_keypoint: bool = True,
                       axis_azimuth: float = 70,
                       axis_limit: float = 1.7,
                       axis_dist: float = 10.0,
                       axis_elev: float = 15.0,
                       num_instances: int = 5,
                       plot_size: int = 300,
                       kpt_thr: float = 0.3) -> None:
        """Draw datasample and save to all backends.

        - If GT and prediction are plotted at the same time, they are
        displayed in a stitched image where the left image is the
        ground truth and the right image is the prediction.
        - If ``show`` is True, all storage backends are ignored, and
        the images will be displayed in a local window.
        - If ``out_file`` is specified, the drawn image will be
        saved to ``out_file``. t is usually used when the display
        is not available.

        Args:
            image (np.ndarray): The image to draw
            data_sample (:obj:`PoseDataSample`): The 3d data sample
                to visualize
            det_data_sample (:obj:`PoseDataSample`, optional): The 2d detection
                data sample to visualize
            draw_2d (bool): Whether to draw 2d detection results. Defaults to
                ``True``
            draw_bbox (bool): Whether to draw bounding boxes. Default to
                ``False``
            show_kpt_idx (bool): Whether to show the index of keypoints.
                Defaults to ``False``
            skeleton_style (str): Skeleton style selection. Defaults to
                ``'mmpose'``
            dataset_2d (str): Name of 2d keypoint dataset. Defaults to
                ``'CocoDataset'``
            dataset_3d (str): Name of 3d keypoint dataset. Defaults to
                ``'Human36mDataset'``
            convert_keypoint (bool): Whether to convert keypoint definition.
                Defaults to ``True``
            axis_azimuth (float): axis azimuth angle for 3D visualizations.
            axis_dist (float): axis distance for 3D visualizations.
            axis_elev (float): axis elevation view angle for 3D visualizations.
            axis_limit (float): The axis limit to visualize 3d pose. The xyz
                range will be set as:
                - x: [x_c - axis_limit/2, x_c + axis_limit/2]
                - y: [y_c - axis_limit/2, y_c + axis_limit/2]
                - z: [0, axis_limit]
                Where x_c, y_c is the mean value of x and y coordinates
            num_instances (int): Number of instances to be shown in 3D. If
                smaller than 0, all the instances in the pose_result will be
                shown. Otherwise, pad or truncate the pose_result to a length
                of num_instances. Defaults to -1
            plot_size (int): The size of the plot. Defaults to 300
            kpt_thr (float, optional): Minimum threshold of keypoints
                to be shown. Default: 0.3.
        """

        pose_2d_data = None
        scores_2d = None

        if draw_2d:
            pose_2d_data = image.copy()

            # draw bboxes & keypoints
            if (det_data_sample is not None
                    and 'pred_instances' in det_data_sample):
                pose_2d_data, scores_2d = self._draw_instances_kpts(
                    image=pose_2d_data,
                    instances=det_data_sample.pred_instances,
                    kpt_thr=kpt_thr,
                    show_kpt_idx=show_kpt_idx,
                    skeleton_style=skeleton_style,
                    track_ids=track_ids)
                if draw_bbox:
                    pose_2d_data = self._draw_instances_bbox(
                        pose_2d_data, det_data_sample.pred_instances)
        if scores_2d is not None and convert_keypoint:
            if scores_2d.ndim == 2:
                scores_2d = scores_2d[..., None]
            scores_2d = np.squeeze(
                convert_keypoint_definition(scores_2d, dataset_2d, dataset_3d),
                axis=-1)
        pose3d_data_dic = self._draw_3d_data_samples(
            data_sample,
            track_ids,
            kpt_thr=kpt_thr,
            num_instances=num_instances,
            plot_size=plot_size,
            axis_azimuth=axis_azimuth,
            axis_limit=axis_limit,
            show_kpt_idx=show_kpt_idx,
            axis_dist=axis_dist,
            axis_elev=axis_elev,
            scores_2d=scores_2d)
        
        if pose_2d_data is not None:
            pose_2d_data = cv2.cvtColor(pose_2d_data, cv2.COLOR_BGR2RGB)

        return pose_2d_data, pose3d_data_dic
